"""Connected repair control uses fresh identity and independent, complete proof."""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from patchpilot.repairs.configuration import apply_changes
from patchpilot.repairs.errors import ConnectedRepairError
from patchpilot.repairs.models import (
    ConfigChange,
    PullRequest,
    RepairProposal,
    SandboxResult,
    SiteManifest,
    VerificationCheck,
)
from patchpilot.repairs.service import RepositoryRepairService
from patchpilot.webscan.models import HTTPResponse, ScanReport

BASE = "a" * 40
BLOB = "b" * 40
IMAGE = "sha256:" + "c" * 64
ORIGINAL = (
    "display_errors = On\ndisplay_startup_errors = On\nlog_errors = Off\n"
    "expose_php = On\nupload_max_filesize = 8M\npost_max_size = 10M\n"
    "; PRIVATE_CONFIG_COMMENT\n"
)
TARGETS = {
    "display_errors": "Off",
    "display_startup_errors": "Off",
    "log_errors": "On",
    "expose_php": "Off",
}
SECURITY = {
    "display_errors",
    "display_startup_errors",
    "log_errors",
    "expose_php",
    "php_banner_hidden",
}
BEHAVIOR = {
    "homepage": {"homepage_status"},
    "contact": {"contact_valid", "contact_invalid"},
    "upload": {"upload_size", "upload_sha256"},
}


def now():
    return datetime.now(UTC).isoformat()


def old():
    return (datetime.now(UTC) - timedelta(hours=2)).isoformat()


def assessment(**update):
    return ScanReport(
        assessment_id="website-real-evidence",
        url="https://site.example/",
        state="COMPLETED",
        created_at=now(),
        finished_at=now(),
    ).model_copy(update=update)


def proposal():
    return RepairProposal(
        rationale="Disable public PHP diagnostics while retaining logging and upload limits.",
        changes=[ConfigChange(key=key, value=value) for key, value in TARGETS.items()],
        model_id="injected-anthropic-model",
        provider_message_id="injected-message",
        input_tokens=20,
        output_tokens=10,
    )


class GitHub:
    def __init__(self, harness):
        self.harness = harness
        self.closed = False
        self.reads = []

    @contextmanager
    def budget(self, seconds):
        assert seconds in {35, 45}
        yield self

    def close(self):
        self.closed = True

    def identity(self):
        return "operator"

    def repository(self, repository):
        assert repository == "owner/site"
        return "main", self.harness.head

    def read_file(self, repository, path, commit, *, limit):
        assert repository == "owner/site"
        assert commit == BASE
        assert limit == 16384
        self.reads.append((path, commit))
        if path == ".patchpilot.json":
            return self.harness.manifest.model_dump_json(
                by_alias=True
            ).encode(), "d" * 40
        assert path == "config/php.ini"
        return self.harness.original.encode(), BLOB

    def source_files(self, repository, document_root, commit):
        assert (
            repository == "owner/site" and document_root == "public" and commit == BASE
        )
        self.harness.source_calls += 1
        return {"index.php": b"<?php echo 'PRIVATE_SOURCE_CONTENT';"}

    def publish_patch(self, **kwargs):
        self.harness.publications.append(kwargs)
        if self.harness.publication_failure:
            raise ConnectedRepairError(
                "GitHub publication needs reconciliation. Retry this same repair."
            )
        if not kwargs["allow_create"] and not self.harness.existing_pr:
            raise ConnectedRepairError(
                "The proof expired before a new pull request could be created."
            )
        return PullRequest(
            url="https://github.com/owner/site/pull/7",
            number=7,
            branch=f"patchpilot/{kwargs['repair_id']}",
            commit="e" * 40,
            draft=not self.harness.existing_pr,
        )


class Marker:
    def __init__(self, harness):
        self.harness = harness
        self.calls = []

    def fetch(self, url, *, timeout_s, max_redirects):
        assert url == "https://site.example/.well-known/patchpilot.json"
        assert timeout_s == 15 and max_redirects == 2
        self.calls.append(url)
        marker = {
            "repository": "owner/site",
            "commit": self.harness.marker_commit,
            "siteId": "site-profile-01",
        }
        response = HTTPResponse(
            url="https://elsewhere.example/marker"
            if self.harness.cross_origin
            else url,
            status=200,
            headers=(),
            body=json.dumps(marker).encode(),
            body_truncated=False,
            elapsed_ms=1,
            resolved_ip="93.184.216.34",
        )
        return (response,)


class Sandbox:
    def __init__(self, harness):
        self.harness, self.calls = harness, []

    def verify(self, files, content, manifest, capabilities, phase, *, run_id):
        assert files == {"index.php": b"<?php echo 'PRIVATE_SOURCE_CONTENT';"}
        assert manifest == self.harness.manifest
        assert run_id == "repair-explicit-intent"
        self.calls.append((phase, content, capabilities[:]))
        required = (
            SECURITY
            | {"runtime_version"}
            | set().union(*(BEHAVIOR[item] for item in capabilities))
        )
        checks = [
            VerificationCheck(
                check_id=check_id,
                label=check_id,
                phase=phase,
                passed=phase == "CANDIDATE"
                or check_id not in SECURITY
                or self.harness.secure,
                expected="fixed assertion",
                observed="normalized observation",
                duration_ms=3,
            )
            for check_id in sorted(required)
        ]
        if phase == "BASELINE" and self.harness.baseline_failure:
            next(
                check for check in checks if check.check_id == "homepage_status"
            ).passed = False
        if phase == "CANDIDATE" and self.harness.candidate_failure:
            next(
                check for check in checks if check.check_id == "homepage_status"
            ).passed = False
        if phase == self.harness.invalid_phase:
            if self.harness.invalid_checks == "missing":
                checks.pop()
            elif self.harness.invalid_checks == "duplicate":
                checks.append(checks[0].model_copy())
            elif self.harness.invalid_checks == "extra":
                checks.append(checks[0].model_copy(update={"check_id": "invented"}))
            else:
                checks[0].phase = "CANDIDATE" if phase == "BASELINE" else "BASELINE"
        digest = (
            "sha256:" + "f" * 64
            if phase == "CANDIDATE" and self.harness.changed_image
            else IMAGE
        )
        return SandboxResult(
            tuple(checks),
            {"php_version": "8.3.36", "expose_php": phase == "BASELINE"},
            digest,
        )


class Planner:
    def __init__(self, harness):
        self.harness, self.closed = harness, False

    def propose(self, **kwargs):
        self.harness.planner_inputs.append(kwargs)
        kwargs["progress"]("Injected provider streamed a bounded proposal")
        if self.harness.planner_failure:
            raise RuntimeError("PRIVATE_PROVIDER_REQUEST")
        return proposal()

    def close(self):
        self.closed = True


class Harness:
    def __init__(self, **options):
        self.head, self.marker_commit, self.original = BASE, BASE, ORIGINAL
        self.manifest = SiteManifest(
            site_id="site-profile-01",
            document_root="public",
            php_ini="config/php.ini",
            capabilities=["homepage", "contact", "upload"],
        )
        self.secure = self.baseline_failure = self.candidate_failure = False
        self.changed_image = self.cross_origin = self.planner_failure = False
        self.publication_failure = self.existing_pr = False
        self.invalid_phase, self.invalid_checks = None, None
        self.source_calls = 0
        self.clients, self.planners, self.publications, self.planner_inputs = (
            [],
            [],
            [],
            [],
        )
        for key, value in options.items():
            setattr(self, key, value)
        self.marker, self.sandbox = Marker(self), Sandbox(self)
        self.service = RepositoryRepairService(
            root="/unused-test-workspace",
            github_factory=self.github,
            public_client=self.marker,
            sandbox=self.sandbox,
            planner_factory=self.planner,
        )

    def github(self):
        client = GitHub(self)
        self.clients.append(client)
        return client

    def planner(self):
        planner = Planner(self)
        self.planners.append(planner)
        return planner

    def connect(self, capabilities=None):
        return self.service.connect(
            assessment(),
            "https://github.com/owner/site",
            capabilities or ["homepage", "contact", "upload"],
        )

    def repair(self, connection=None):
        snapshots = []
        report = self.service.repair(
            connection or self.connect(),
            repair_id="repair-explicit-intent",
            emit=snapshots.append,
        )
        return report, snapshots


def test_connection_pins_declared_deployment_and_selected_checks_without_running_repairs():
    harness = Harness()
    connection = harness.connect(["homepage", "upload"])
    assert connection.repository == "owner/site"
    assert connection.base_commit == BASE
    assert connection.capabilities == ["homepage", "upload"]
    assert connection.site_id == connection.manifest.site_id
    assert "not independent build attestation" in connection.identity_explanation
    assert harness.marker.calls == ["https://site.example/.well-known/patchpilot.json"]
    assert harness.clients[0].reads == [
        (".patchpilot.json", BASE),
        ("config/php.ini", BASE),
    ]
    assert harness.clients[0].closed
    assert (
        not harness.sandbox.calls and not harness.planners and not harness.publications
    )


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "unfinished",
        "failed",
        "non-homepage",
        "unsupported-check",
        "duplicate-check",
        "marker-mismatch",
        "marker-cross-origin",
    ],
)
def test_connection_rejects_missing_freshness_scope_or_declared_identity(change):
    harness = Harness()
    scan, capabilities = assessment(), ["homepage"]
    if change == "expired":
        scan.finished_at = old()
    elif change == "unfinished":
        scan.finished_at = None
    elif change == "failed":
        scan.state = "FAILED"
    elif change == "non-homepage":
        scan.url = "https://site.example/account.php"
    elif change == "unsupported-check":
        harness.manifest.capabilities = ["homepage"]
        capabilities.append("upload")
    elif change == "duplicate-check":
        capabilities.append("homepage")
    elif change == "marker-mismatch":
        harness.marker_commit = "f" * 40
    else:
        harness.cross_origin = True
    with pytest.raises(ConnectedRepairError):
        harness.service.connect(scan, "https://github.com/owner/site", capabilities)
    assert (
        not harness.planners and not harness.sandbox.calls and not harness.publications
    )
    assert all(client.closed for client in harness.clients)


def test_actual_baseline_proposal_and_candidate_produce_separate_deep_snapshots():
    harness = Harness()
    report, snapshots = harness.repair()
    assert report.state == "READY_TO_PUBLISH"
    assert [item.state for item in snapshots] == [
        "FETCHING",
        "BASELINE",
        "PLANNING",
        "PLANNING",
        "STAGING",
        "READY_TO_PUBLISH",
    ]
    assert snapshots[0].checks == []
    assert snapshots[2].patch is None
    assert snapshots[-1] is not report
    assert all(
        [event.sequence for event in item.events]
        == list(range(1, len(item.events) + 1))
        for item in snapshots
    )
    assert any(not check.passed for check in report.checks if check.phase == "BASELINE")
    assert all(check.passed for check in report.checks if check.phase == "CANDIDATE")
    assert len(report.checks) == 22
    assert [call[0] for call in harness.sandbox.calls] == ["BASELINE", "CANDIDATE"]
    candidate, diff = apply_changes(ORIGINAL, proposal().changes, "config/php.ini")
    assert harness.sandbox.calls[-1][1] == candidate
    assert report.patch.unified_diff == diff
    assert report.patch.after_sha256 == hashlib.sha256(candidate.encode()).hexdigest()
    assert (
        "upload_max_filesize = 8M\npost_max_size = 10M\n; PRIVATE_CONFIG_COMMENT\n"
        in candidate
    )
    assert "upload_max_filesize" not in diff
    assert harness.planners[0].closed
    assert all(client.closed for client in harness.clients)
    normalized = {
        key: value
        for key, value in harness.planner_inputs[0].items()
        if key != "progress"
    }
    assert not any(
        secret in str(normalized)
        for secret in (
            "site.example",
            "PRIVATE_SOURCE_CONTENT",
            "PRIVATE_CONFIG_COMMENT",
        )
    )
    assert not harness.publications
    report.checks[0].observed = "Changed caller object"
    report.events[0].message = "Changed caller event"
    assert snapshots[-1].checks[0].observed == "normalized observation"
    assert snapshots[-1].events[0].message != "Changed caller event"


def test_failing_baseline_stops_before_provider_or_candidate():
    harness = Harness(baseline_failure=True)
    report, snapshots = harness.repair()
    assert report.state == "REJECTED"
    assert snapshots[-1].state == "REJECTED"
    assert report.proposal is None and report.patch is None
    assert len(harness.sandbox.calls) == 1
    assert not harness.planners and not harness.publications


@pytest.mark.parametrize("phase", ["BASELINE", "CANDIDATE"])
@pytest.mark.parametrize("malformed", ["missing", "duplicate", "extra", "wrong-phase"])
def test_incomplete_duplicate_or_wrong_phase_evidence_can_never_be_ready(
    phase, malformed
):
    harness = Harness(invalid_phase=phase, invalid_checks=malformed)
    report, snapshots = harness.repair()
    assert report.state == "FAILED"
    assert all(snapshot.state != "READY_TO_PUBLISH" for snapshot in snapshots)
    assert not harness.publications
    if phase == "BASELINE":
        assert not harness.planners


@pytest.mark.parametrize(
    "options", [{"candidate_failure": True}, {"changed_image": True}]
)
def test_failed_candidate_or_changed_image_retains_proposal_without_accepting_it(
    options,
):
    harness = Harness(**options)
    report, snapshots = harness.repair()
    assert report.state == "REJECTED"
    assert report.patch and report.proposal and report.finished_at
    assert len(report.checks) == 22
    assert not any(snapshot.state == "READY_TO_PUBLISH" for snapshot in snapshots)
    assert not harness.publications


def test_provider_failure_retains_baseline_without_generating_a_fallback_patch():
    harness = Harness(planner_failure=True)
    report, _ = harness.repair()
    assert report.state == "FAILED"
    assert len(report.checks) == 11
    assert report.proposal is None and report.patch is None
    assert "PRIVATE_PROVIDER" not in report.model_dump_json()
    assert harness.planners[0].closed
    assert len(harness.sandbox.calls) == 1
    assert not harness.publications


def test_secure_configuration_returns_no_change_without_provider_or_publication():
    secure, _ = apply_changes(ORIGINAL, proposal().changes, "config/php.ini")
    harness = Harness(original=secure, secure=True)
    report, _ = harness.repair()
    assert report.state == "NO_CHANGE"
    assert report.patch is None and report.proposal is None
    assert len(harness.sandbox.calls) == 1
    assert not harness.planners and not harness.publications


@pytest.mark.parametrize(
    "change", ["expired", "moved-head", "changed-marker", "changed-manifest"]
)
def test_connection_is_revalidated_before_any_untrusted_source_execution(change):
    harness = Harness()
    connection = harness.connect()
    if change == "expired":
        connection.created_at = old()
    elif change == "moved-head":
        harness.head = "f" * 40
    elif change == "changed-marker":
        harness.marker_commit = "f" * 40
    else:
        harness.manifest = harness.manifest.model_copy(
            update={"php_ini": "config/changed.ini"}
        )
    report, _ = harness.repair(connection)
    assert report.state == "FAILED"
    assert report.checks == [] and report.patch is None
    assert (
        not harness.sandbox.calls and not harness.planners and not harness.publications
    )


def test_explicit_publication_uses_the_exact_verified_bytes_and_preserves_all_proof():
    harness = Harness()
    connection = harness.connect()
    report, _ = harness.repair(connection)
    before = report.model_copy(deep=True)
    snapshots = []
    report.state = "PUBLISHING"
    published = harness.service.publish(connection, report, emit=snapshots.append)
    assert published.state == "PUBLISHED"
    assert published.patch == before.patch and published.proposal == before.proposal
    assert published.checks == before.checks
    assert published.pull_request.draft
    assert snapshots[-1].state == "PUBLISHED"
    assert len(harness.planners) == 1 and len(harness.sandbox.calls) == 2
    request = harness.publications[0]
    candidate, _ = apply_changes(ORIGINAL, proposal().changes, "config/php.ini")
    assert request["candidate"] == candidate.encode()
    assert request["base_commit"] == BASE and request["path"] == "config/php.ini"
    assert request["allow_create"] is True
    assert "has not been deployed" in request["body"]
    assert before.patch.after_sha256 in request["body"]
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "diff",
        "before-blob",
        "path",
        "weak-proposal",
        "missing-proof",
        "duplicate-proof",
        "failing-candidate",
        "image",
        "wrong-connection",
    ],
)
def test_publication_rejects_modified_or_incomplete_verified_proof(change):
    harness = Harness()
    connection = harness.connect()
    report, _ = harness.repair(connection)
    if change == "hash":
        report.patch.after_sha256 = "f" * 64
    elif change == "diff":
        report.patch.unified_diff += "unverified change"
    elif change == "before-blob":
        report.patch.before_blob_sha = "f" * 40
    elif change == "path":
        report.patch.path = "public/index.php"
    elif change == "weak-proposal":
        report.proposal.changes[0].value = "On"
    elif change == "missing-proof":
        report.checks.pop()
    elif change == "duplicate-proof":
        report.checks.append(report.checks[-1].model_copy())
    elif change == "failing-candidate":
        report.checks[-1].passed = False
    elif change == "image":
        report.image_digest = "unapproved-image:latest"
    else:
        report.connection_id = "different-connection"
    with pytest.raises(ConnectedRepairError):
        harness.service.publish(connection, report, emit=lambda _: None)
    assert not harness.publications


@pytest.mark.parametrize("existing", [False, True])
def test_expired_publication_can_reconcile_existing_pr_but_cannot_create_one(existing):
    harness = Harness(existing_pr=existing)
    connection = harness.connect()
    report, _ = harness.repair(connection)
    connection.created_at, report.created_at = old(), old()
    report.state = "PUBLISHING"
    if existing:
        result = harness.service.publish(connection, report, emit=lambda _: None)
        assert result.state == "PUBLISHED"
        assert result.pull_request.draft is False
    else:
        with pytest.raises(ConnectedRepairError, match="expired"):
            harness.service.publish(connection, report, emit=lambda _: None)
    assert harness.publications[0]["allow_create"] is False
    assert len(harness.planners) == 1 and len(harness.sandbox.calls) == 2


def test_publication_failure_never_claims_success_or_runs_the_provider_again():
    harness = Harness(publication_failure=True)
    connection = harness.connect()
    report, _ = harness.repair(connection)
    snapshots = []
    report.state = "PUBLISHING"
    with pytest.raises(ConnectedRepairError, match="reconciliation"):
        harness.service.publish(connection, report, emit=snapshots.append)
    assert report.state == "PUBLISHING" and report.pull_request is None
    assert snapshots == []
    assert len(harness.planners) == 1 and len(harness.sandbox.calls) == 2
    assert harness.clients[-1].closed


def test_pr_body_only_describes_business_checks_actually_selected():
    harness = Harness()
    connection = harness.connect(["homepage"])
    report, _ = harness.repair(connection)
    body = harness.service._pull_request_body(report)
    assert "homepage_status" in body
    assert "contact check" not in body.lower()
    assert "upload check" not in body.lower()
    assert "real 3 MiB" not in body


def test_status_only_exposes_local_identity_and_safe_setup_message():
    harness = Harness()
    assert harness.service.status().model_dump() == {
        "available": True,
        "login": "operator",
        "message": "Using the GitHub account signed in on this computer. Choose a repository you control.",
    }
    assert harness.clients[-1].closed

    def unavailable():
        raise ConnectedRepairError("PRIVATE_LOCAL_TOKEN")

    harness.service.github_factory = unavailable
    status = harness.service.status()
    assert status.available is False and status.login is None
    assert "PRIVATE_LOCAL" not in status.model_dump_json()
