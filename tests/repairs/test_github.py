import base64
import json

import httpx
import pytest

from patchpilot.repairs.errors import ConnectedRepairError
from patchpilot.repairs.github import GitHubClient, blob_sha, repository_name

BASE, COMMIT, TREE = "a" * 40, "b" * 40, "c" * 40
CONTENT = b"expose_php = Off\n"
BRANCH = "patchpilot/repair-testing123"


class GitHubServer:
    def __init__(self):
        self.head, self.branch, self.pull = BASE, None, None
        self.mode, self.timeout_after_pr = "100644", False
        self.writes = []

    def handle(self, request):
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == "Bearer LOCAL_TEST_TOKEN"
        path = "/" + "/".join(request.url.path.split("/")[4:])
        method = request.method
        if method == "POST":
            data = json.loads(request.content)
            self.writes.append((path, data))
        if path == "/":
            result = {
                "full_name": "owner/site",
                "default_branch": "main",
                "permissions": {"push": True},
            }
        elif path == "/git/ref/heads/main":
            result = {"object": {"sha": self.head}}
        elif path == f"/git/ref/heads/{BRANCH}":
            if self.branch is None:
                return httpx.Response(404, json={})
            result = {"object": {"sha": self.branch}}
        elif path.startswith("/git/trees/"):
            result = {
                "truncated": False,
                "tree": [
                    {
                        "path": "config/php.ini",
                        "type": "blob",
                        "mode": self.mode,
                        "sha": blob_sha(CONTENT),
                        "size": len(CONTENT),
                    }
                ],
            }
        elif path == "/contents/config/php.ini":
            result = {
                "type": "file",
                "encoding": "base64",
                "sha": blob_sha(CONTENT),
                "size": len(CONTENT),
                "content": base64.b64encode(CONTENT).decode(),
            }
        elif path.startswith("/compare/"):
            result = {
                "ahead_by": 1,
                "behind_by": 0,
                "files": [
                    {
                        "filename": "config/php.ini",
                        "status": "modified",
                        "sha": blob_sha(CONTENT),
                    }
                ],
            }
        elif path == "/git/blobs":
            assert data == {
                "content": base64.b64encode(CONTENT).decode(),
                "encoding": "base64",
            }
            result = {"sha": blob_sha(CONTENT)}
        elif path == f"/git/commits/{BASE}":
            result = {"tree": {"sha": TREE}}
        elif path == "/git/trees":
            assert data["tree"] == [
                {
                    "path": "config/php.ini",
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha(CONTENT),
                }
            ]
            result = {"sha": TREE}
        elif path == "/git/commits":
            assert data["parents"] == [BASE]
            result = {"sha": COMMIT}
        elif path == "/git/refs":
            assert data == {"ref": f"refs/heads/{BRANCH}", "sha": COMMIT}
            assert self.branch is None
            self.branch = COMMIT
            result = {"object": {"sha": COMMIT}}
        elif path == "/pulls" and method == "POST":
            assert data["draft"] is True and data["head"] == BRANCH
            self.pull = {
                "number": 1,
                "html_url": "https://github.com/owner/site/pull/1",
                "draft": True,
                "head": {"sha": COMMIT, "ref": BRANCH},
                "base": {"ref": "main"},
            }
            if self.timeout_after_pr:
                raise httpx.ReadTimeout("TEST_SERVER_PRIVATE_ERROR", request=request)
            result = self.pull
        elif path == "/pulls":
            result = [self.pull] if self.pull else []
        else:
            raise AssertionError((method, path))
        return httpx.Response(201 if method == "POST" else 200, json=result)


def publish(client, **overrides):
    return client.publish_patch(
        **{
            "repository": "owner/site",
            "base_branch": "main",
            "base_commit": BASE,
            "repair_id": "repair-testing123",
            "path": "config/php.ini",
            "candidate": CONTENT,
            "body": "Independent test evidence",
            **overrides,
        }
    )


def test_actual_rest_creation_is_exact_one_file_draft_and_retry_reconciles():
    server = GitHubServer()
    client = GitHubClient(
        "LOCAL_TEST_TOKEN", transport=httpx.MockTransport(server.handle)
    )
    first = publish(client)
    assert first.url == "https://github.com/owner/site/pull/1"
    assert first.commit == COMMIT and first.draft
    count = len(server.writes)
    assert count == 5
    assert publish(client) == first
    assert len(server.writes) == count
    server.head = "f" * 40
    assert publish(client, repository="OWNER/SITE", allow_create=False) == first
    assert len(server.writes) == count
    client.close()


def test_unknown_pr_creation_outcome_is_recovered_without_duplicate_writes():
    server = GitHubServer()
    server.timeout_after_pr = True
    client = GitHubClient(
        "LOCAL_TEST_TOKEN", transport=httpx.MockTransport(server.handle)
    )
    with pytest.raises(ConnectedRepairError, match="reconciliation") as error:
        publish(client)
    assert "PRIVATE_ERROR" not in str(error.value)
    count = len(server.writes)
    assert publish(client).number == 1
    assert len(server.writes) == count
    client.close()


def test_stale_base_prevents_all_external_writes():
    server = GitHubServer()
    server.head = "f" * 40
    client = GitHubClient(
        "LOCAL_TEST_TOKEN", transport=httpx.MockTransport(server.handle)
    )
    with pytest.raises(ConnectedRepairError, match="moved"):
        publish(client)
    assert server.writes == []
    client.close()


@pytest.mark.parametrize("mode", ["120000", "160000", "100755"])
def test_contents_api_symlink_resolution_cannot_bypass_pinned_regular_file_mode(mode):
    server = GitHubServer()
    server.mode = mode
    client = GitHubClient(
        "LOCAL_TEST_TOKEN", transport=httpx.MockTransport(server.handle)
    )
    with pytest.raises(ConnectedRepairError, match="regular non-executable"):
        client.read_file("owner/site", "config/php.ini", BASE)
    assert server.writes == []
    client.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/o/r",
        "https://github.com@evil.example/o/r",
        "https://github.com/o/r?token=PRIVATE",
        "https://github.com/o/r/tree/main",
        "https://127.0.0.1/o/r",
        "https://github.com/o/..",
    ],
)
def test_repository_url_must_be_an_exact_public_github_repository(url):
    with pytest.raises(ConnectedRepairError):
        repository_name(url)


def test_repository_git_suffix_is_normalized():
    assert repository_name("https://github.com/owner/site.git") == "owner/site"
