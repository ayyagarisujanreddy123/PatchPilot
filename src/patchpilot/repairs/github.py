"""Bounded GitHub REST access, pinned source snapshots, and retry-safe draft PRs."""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from dotenv import dotenv_values

from patchpilot.repairs.errors import ConnectedRepairError
from patchpilot.repairs.models import PullRequest

SHA = re.compile(r"[a-f0-9]{40}")


def repository_name(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        raise ConnectedRepairError("Use a valid HTTPS GitHub repository URL.") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise ConnectedRepairError(
            "Use a GitHub repository URL such as https://github.com/owner/repository."
        )
    parts = parsed.path.strip("/").split("/")
    if (
        len(parts) >= 4
        and parts[2] == "tree"
        and all(part not in {"", ".", ".."} for part in parts)
    ):
        # Browser branch links identify the repository; repairs still pin its
        # authoritative default-branch/deployment commit, never this URL suffix.
        parts = parts[:2]
    if len(parts) != 2:
        raise ConnectedRepairError(
            "Choose a repository home URL or its GitHub branch page, such as /tree/main."
        )
    owner, repo = parts
    repo = repo.removesuffix(".git")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo)
        or repo in {".", ".."}
    ):
        raise ConnectedRepairError("The GitHub repository name is invalid.")
    return f"{owner}/{repo}"


def checked_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ConnectedRepairError(
            "GitHub returned an invalid commit or source identity."
        )
    return value


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(content)}\0".encode() + content, usedforsecurity=False
    ).hexdigest()


def credentials(root: Path) -> str:
    token = os.environ.get("GITHUB_TOKEN") or dotenv_values(
        root / ".env", interpolate=False
    ).get("GITHUB_TOKEN")
    if token and token.strip():
        return token.strip()
    if shutil.which("gh"):
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if result.returncode == 0 and 0 < len(result.stdout.strip()) < 1024:
            return result.stdout.strip()
    raise ConnectedRepairError(
        "Sign in to GitHub on this computer with gh auth login, or set GITHUB_TOKEN locally. Repository contents and pull-request write permission are needed."
    )


class GitHubClient:
    def __init__(self, token: str, *, transport=None):
        self.client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.expires = time.monotonic() + 45
        self._trees = {}

    @classmethod
    def from_environment(cls, root: Path):
        return cls(credentials(root))

    @contextmanager
    def budget(self, seconds=45):
        self.expires = time.monotonic() + seconds
        yield self

    def close(self):
        self.client.close()

    def request(self, method, path, *, json_body=None, params=None, missing=False):
        remaining = self.expires - time.monotonic()
        if remaining <= 0:
            raise ConnectedRepairError(
                "GitHub exceeded this operation's time budget. Retry after reviewing the recorded state."
            )
        if not path.startswith("/repos/") and path != "/user":
            raise ConnectedRepairError("Unsupported GitHub API destination.")
        timer = threading.Timer(remaining, self.client.close)
        timer.daemon = True
        timer.start()
        try:
            with self.client.stream(
                method, path, json=json_body, params=params, timeout=min(10, remaining)
            ) as response:
                if response.status_code == 404 and missing:
                    return None
                if response.status_code not in {200, 201}:
                    raise ConnectedRepairError(
                        f"GitHub request failed (HTTP {response.status_code}). Check repository access and retry; no response body was retained."
                    )
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > 4 * 1024 * 1024 or time.monotonic() > self.expires:
                        raise ConnectedRepairError(
                            "GitHub response exceeded the size or time limit."
                        )
                return json.loads(body)
        except (httpx.HTTPError, json.JSONDecodeError, RuntimeError):
            raise ConnectedRepairError(
                "GitHub could not complete the operation. Its outcome may need reconciliation; retry the same repair rather than creating a new one."
            ) from None
        finally:
            timer.cancel()

    def identity(self):
        data = self.request("GET", "/user")
        login = data.get("login") if isinstance(data, dict) else None
        if not isinstance(login, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", login
        ):
            raise ConnectedRepairError(
                "GitHub did not return a valid signed-in account."
            )
        return login

    def repository(self, repository):
        data = self.request("GET", f"/repos/{repository}")
        if (
            not isinstance(data, dict)
            or str(data.get("full_name", "")).lower() != repository.lower()
            or not isinstance(data.get("permissions"), dict)
            or data["permissions"].get("push") is not True
            or data.get("archived") is True
            or data.get("disabled") is True
        ):
            raise ConnectedRepairError(
                "The signed-in account needs write access to an active repository. Fork a demo repository into your account if necessary."
            )
        branch = data.get("default_branch")
        if (
            not isinstance(branch, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,180}", branch)
            or any(part in {"", ".", ".."} for part in branch.split("/"))
        ):
            raise ConnectedRepairError(
                "This repository's default branch is unsupported."
            )
        return branch, self.head(repository, branch)

    def head(self, repository, branch, *, missing=False):
        data = self.request(
            "GET",
            f"/repos/{repository}/git/ref/heads/{quote(branch, safe='/')}",
            missing=missing,
        )
        if data is None:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("object"), dict):
            raise ConnectedRepairError("GitHub returned an invalid branch reference.")
        return checked_sha(data["object"].get("sha"))

    def _decode(self, data, *, limit):
        if (
            not isinstance(data, dict)
            or data.get("encoding") != "base64"
            or not isinstance(data.get("content"), str)
            or type(data.get("size")) is not int
            or not 0 <= data["size"] <= limit
        ):
            raise ConnectedRepairError(
                "A repository file is unsupported or exceeds the source limit."
            )
        try:
            content = base64.b64decode(data["content"].replace("\n", ""), validate=True)
        except ValueError:
            raise ConnectedRepairError(
                "GitHub returned invalid source content."
            ) from None
        if (
            len(content) != data["size"]
            or len(content) > limit
            or blob_sha(content) != checked_sha(data.get("sha"))
        ):
            raise ConnectedRepairError(
                "Repository source content did not match its Git object identity."
            )
        return content, data["sha"]

    def read_file(self, repository, path, commit, *, limit=262144):
        entry = next(
            (item for item in self.tree(repository, commit) if item["path"] == path),
            None,
        )
        if (
            entry is None
            or entry.get("type") != "blob"
            or entry.get("mode") != "100644"
        ):
            raise ConnectedRepairError(
                "The profile and PHP configuration must be regular non-executable Git files, not symlinks or submodules."
            )
        data = self.request(
            "GET",
            f"/repos/{repository}/contents/{quote(path, safe='/')}",
            params={"ref": checked_sha(commit)},
        )
        if not isinstance(data, dict) or data.get("type") != "file" or "target" in data:
            raise ConnectedRepairError(
                "The supported profile requires regular files, not links or submodules."
            )
        content, identity = self._decode(data, limit=limit)
        if identity != entry.get("sha") or len(content) != entry.get("size"):
            raise ConnectedRepairError(
                "The source file differs from its pinned tree entry."
            )
        return content, identity

    def tree(self, repository, commit):
        key = (repository, checked_sha(commit))
        if key in self._trees:
            return self._trees[key]
        data = self.request(
            "GET", f"/repos/{repository}/git/trees/{commit}", params={"recursive": "1"}
        )
        if (
            not isinstance(data, dict)
            or data.get("truncated") is not False
            or not isinstance(data.get("tree"), list)
            or len(data["tree"]) > 5000
            or any(
                not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                for entry in data["tree"]
            )
        ):
            raise ConnectedRepairError(
                "The repository tree is too large, invalid, or incomplete for this supported profile."
            )
        paths = [entry["path"] for entry in data["tree"]]
        if len(paths) != len(set(paths)):
            raise ConnectedRepairError("GitHub returned duplicate source paths.")
        self._trees[key] = data["tree"]
        return data["tree"]

    def source_files(self, repository, document_root, commit):
        files, total = {}, 0
        prefix = document_root + "/"
        for entry in self.tree(repository, commit):
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ConnectedRepairError("GitHub returned an invalid source tree.")
            path = entry["path"]
            if not path.startswith(prefix) or entry.get("type") == "tree":
                continue
            relative = path[len(prefix) :]
            if (
                not re.fullmatch(r"[A-Za-z0-9_.-][A-Za-z0-9_./-]{0,180}", relative)
                or any(part in {"", ".", ".."} for part in relative.split("/"))
                or entry.get("type") != "blob"
                or entry.get("mode") not in {"100644", "100755"}
                or type(entry.get("size")) is not int
                or not 0 <= entry["size"] <= 262144
                or relative in files
            ):
                raise ConnectedRepairError(
                    "Source contains an unsafe path, symlink, submodule, or oversized file."
                )
            total += entry["size"]
            if len(files) >= 100 or total > 4 * 1024 * 1024:
                raise ConnectedRepairError(
                    "The supported profile is limited to 100 public files and 4 MiB of source."
                )
            raw = self.request(
                "GET", f"/repos/{repository}/git/blobs/{checked_sha(entry.get('sha'))}"
            )
            content, identity = self._decode(raw, limit=262144)
            if identity != entry["sha"] or len(content) != entry["size"]:
                raise ConnectedRepairError("Source tree and blob identities differ.")
            files[relative] = content
        if not files or "index.php" not in files:
            raise ConnectedRepairError(
                "The supported PHP document root must contain index.php."
            )
        return files

    def _verified_branch(self, repository, branch, base, path, candidate):
        commit = self.head(repository, branch, missing=True)
        if commit is None:
            return None
        comparison = self.request(
            "GET", f"/repos/{repository}/compare/{base}...{commit}"
        )
        files = comparison.get("files", []) if isinstance(comparison, dict) else []
        if (
            not isinstance(comparison, dict)
            or comparison.get("ahead_by") != 1
            or comparison.get("behind_by") != 0
            or len(files) != 1
            or files[0].get("filename") != path
            or files[0].get("status") != "modified"
            or files[0].get("sha") != blob_sha(candidate)
        ):
            raise ConnectedRepairError(
                "The repair branch has changed or conflicts with this verified patch. No reference was overwritten."
            )
        actual, _ = self.read_file(repository, path, commit, limit=16384)
        if actual != candidate:
            raise ConnectedRepairError(
                "The published file no longer matches the verified candidate."
            )
        return commit

    def _existing_pr(self, repository, branch, base_branch, commit):
        pulls = self.request(
            "GET",
            f"/repos/{repository}/pulls",
            params={
                "state": "all",
                "head": f"{repository.split('/')[0]}:{branch}",
                "base": base_branch,
                "per_page": 100,
            },
        )
        if not isinstance(pulls, list):
            raise ConnectedRepairError("GitHub returned an invalid pull-request list.")
        if len(pulls) > 1:
            raise ConnectedRepairError(
                "More than one pull request refers to this repair; review GitHub before retrying."
            )
        if not pulls:
            return None
        data = pulls[0]
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("head"), dict)
            or not isinstance(data.get("base"), dict)
            or data.get("head", {}).get("sha") != commit
            or data.get("head", {}).get("ref") != branch
            or data.get("base", {}).get("ref") != base_branch
            or type(data.get("number")) is not int
        ):
            raise ConnectedRepairError(
                "The existing pull request does not match this verified repair."
            )
        expected = f"https://github.com/{repository}/pull/{data['number']}"
        actual_url = data.get("html_url")
        if not isinstance(actual_url, str) or actual_url.lower() != expected.lower():
            raise ConnectedRepairError(
                "GitHub returned an unexpected pull-request destination."
            )
        return PullRequest(
            url=actual_url,
            number=data["number"],
            branch=branch,
            commit=commit,
            draft=data.get("draft") is True,
        )

    def publish_patch(
        self,
        *,
        repository,
        base_branch,
        base_commit,
        repair_id,
        path,
        candidate: bytes,
        body,
        allow_create=True,
    ):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", repair_id):
            raise ConnectedRepairError("Invalid repair identity.")
        branch = f"patchpilot/{repair_id}"
        commit = self._verified_branch(repository, branch, base_commit, path, candidate)
        if commit:
            existing = self._existing_pr(repository, branch, base_branch, commit)
            if existing:
                return existing
        if not allow_create:
            raise ConnectedRepairError(
                "This proof has expired. Existing publication was checked; prepare a fresh verified repair before creating a new pull request."
            )
        actual_branch, head = self.repository(repository)
        if actual_branch != base_branch or head != base_commit:
            raise ConnectedRepairError(
                "The repository default branch moved. Reconnect the updated deployment and rerun verification; the old proof was not published."
            )
        if not commit:
            blob = self.request(
                "POST",
                f"/repos/{repository}/git/blobs",
                json_body={
                    "content": base64.b64encode(candidate).decode(),
                    "encoding": "base64",
                },
            )
            if not isinstance(blob, dict) or checked_sha(blob.get("sha")) != blob_sha(
                candidate
            ):
                raise ConnectedRepairError(
                    "GitHub did not retain the exact verified configuration blob."
                )
            parent = self.request(
                "GET", f"/repos/{repository}/git/commits/{base_commit}"
            )
            tree = self.request(
                "POST",
                f"/repos/{repository}/git/trees",
                json_body={
                    "base_tree": checked_sha(parent["tree"]["sha"]),
                    "tree": [
                        {
                            "path": path,
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob["sha"],
                        }
                    ],
                },
            )
            created = self.request(
                "POST",
                f"/repos/{repository}/git/commits",
                json_body={
                    "message": f"fix: harden PHP runtime settings\n\nPatchPilot repair {repair_id}",
                    "tree": checked_sha(tree.get("sha")),
                    "parents": [base_commit],
                },
            )
            commit = checked_sha(created.get("sha"))
            self.request(
                "POST",
                f"/repos/{repository}/git/refs",
                json_body={"ref": f"refs/heads/{branch}", "sha": commit},
            )
            if (
                self._verified_branch(repository, branch, base_commit, path, candidate)
                != commit
            ):
                raise ConnectedRepairError(
                    "GitHub branch verification did not match the tested commit."
                )
        if self.head(repository, base_branch) != base_commit:
            raise ConnectedRepairError(
                "The repository changed during publication. The prepared branch was retained; rerun against the current deployment before opening a PR."
            )
        self.request(
            "POST",
            f"/repos/{repository}/pulls",
            json_body={
                "title": "Harden PHP error handling and version disclosure",
                "head": branch,
                "base": base_branch,
                "body": body,
                "draft": True,
            },
        )
        result = self._existing_pr(repository, branch, base_branch, commit)
        if result is None:
            raise ConnectedRepairError(
                "GitHub publication needs reconciliation. Retry this same repair to recover its pull request."
            )
        return result
