"""Connected repairs exercise real admission/storage with finite injected services."""

import json
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from patchpilot.backend.app import create_app
from patchpilot.backend.fake import FakeRepairService
from patchpilot.backend.repository_jobs import StoredConnection, StoredRepair
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.repairs.models import (
    ConfigChange,
    GitHubStatus,
    PullRequest,
    RepairProposal,
    RepositoryConnection,
    RepositoryPatch,
    RepositoryRepairReport,
    SiteManifest,
    VerificationCheck,
)
from patchpilot.webscan.models import ScanReport


def now():
    return datetime.now(UTC).isoformat()


class CompletingWebsite:
    def run(self, url, *, assessment_id, emit):
        return ScanReport(
            assessment_id=assessment_id,
            url=url,
            state="COMPLETED",
            created_at=now(),
            finished_at=now(),
        )


class RepositoryService:
    def __init__(
        self, directory, *, repair_failure=False, publication_failure=False, gate=None
    ):
        self.directory = directory
        self.repair_failure, self.publication_failure, self.gate = (
            repair_failure,
            publication_failure,
            gate,
        )
        self.connect_calls = self.repair_calls = self.publish_calls = 0
        self.entered, self.allow = threading.Event(), threading.Event()
        self.checkpoint = None
        self.finished = False

    def status(self):
        return GitHubStatus(
            available=True, login="test-operator", message="Local account available"
        )

    def connect(self, assessment, repository_url, capabilities):
        self.connect_calls += 1
        if repository_url != "https://github.com/operator/php-site":
            raise ValueError(
                "Choose a GitHub repository with a matching deployment marker"
            )
        return RepositoryConnection(
            connection_id=f"connection-{uuid4().hex}",
            assessment_id=assessment.assessment_id,
            url=assessment.url,
            repository="operator/php-site",
            repository_url=repository_url,
            default_branch="main",
            base_commit="a" * 40,
            site_id="test-site-01",
            manifest=SiteManifest(
                site_id="test-site-01",
                document_root="public",
                php_ini="php.ini",
                capabilities=capabilities,
            ),
            capabilities=capabilities,
            created_at=now(),
        )

    def _read_checkpoint(self, repair_id):
        return json.loads(
            (self.directory / "reports" / f"{repair_id}.json").read_text()
        )

    def repair(self, connection, *, repair_id, emit):
        self.repair_calls += 1
        report = RepositoryRepairReport(
            repair_id=repair_id,
            connection_id=connection.connection_id,
            assessment_id=connection.assessment_id,
            repository=connection.repository,
            url=connection.url,
            base_commit=connection.base_commit,
            capabilities=connection.capabilities,
            created_at=now(),
            state="BASELINE",
            checks=[
                VerificationCheck(
                    check_id="homepage",
                    label="Homepage",
                    phase="BASELINE",
                    passed=True,
                    expected="200",
                    observed="200",
                )
            ],
        )
        emit(report)
        self.checkpoint = self._read_checkpoint(repair_id)
        if self.gate == "repair":
            self.entered.set()
            if not self.allow.wait(5):
                raise RuntimeError("Test gate timed out")
        if self.repair_failure:
            raise RuntimeError("PRIVATE_PROVIDER_KEY_MUST_NOT_LEAK")
        report.state, report.finished_at = "READY_TO_PUBLISH", now()
        report.checks.append(
            VerificationCheck(
                check_id="homepage",
                label="Homepage",
                phase="CANDIDATE",
                passed=True,
                expected="200",
                observed="200",
            )
        )
        report.proposal = RepairProposal(
            rationale="Hide the runtime banner",
            changes=[ConfigChange(key="expose_php", value="Off")],
            model_id="injected-provider",
            provider_message_id="test-message",
            input_tokens=10,
            output_tokens=5,
        )
        report.patch = RepositoryPatch(
            path="php.ini",
            before_blob_sha="b" * 40,
            after_sha256="c" * 64,
            unified_diff="--- a/php.ini\n+++ b/php.ini\n@@ -1 +1 @@\n-expose_php=On\n+expose_php=Off\n",
        )
        self.finished = True
        return report

    def publish(self, connection, report, *, emit):
        self.publish_calls += 1
        assert report.state == "PUBLISHING"
        self.checkpoint = self._read_checkpoint(report.repair_id)
        assert self.checkpoint["publicationStartedAt"]
        assert self.checkpoint["publicationKeyHash"]
        assert self.checkpoint["report"]["state"] == "PUBLISHING"
        if self.gate == "publish":
            self.entered.set()
            if not self.allow.wait(5):
                raise RuntimeError("Test gate timed out")
        if self.publication_failure and self.publish_calls == 1:
            raise RuntimeError("PRIVATE_GITHUB_TOKEN_MUST_NOT_LEAK")
        report.state, report.finished_at = "PUBLISHED", now()
        report.pull_request = PullRequest(
            url="https://github.com/operator/php-site/pull/17",
            number=17,
            branch=f"patchpilot/{report.repair_id}",
            commit="d" * 40,
        )
        return report


@contextmanager
def repository_client(tmp_path, service):
    runs, events, recipes = (
        FileRunStore(tmp_path / "runs"),
        FileEventSink(tmp_path / "runs"),
        FileRecipeStore(tmp_path / "recipes"),
    )
    repair = FakeRepairService(runs, events, recipes, step_delay=0.001)
    app = create_app(
        runs,
        events,
        recipes,
        repair,
        custom_website_agent=CompletingWebsite(),
        custom_repository_service=service,
    )
    with TestClient(app) as client:
        establish_session(client)
        yield client


def establish_session(client):
    token = client.get("/api/session").json()["csrfToken"]
    client.headers.update({"X-CSRF-Token": token, "Origin": "http://testserver"})


def wait_state(client, url, states):
    for _ in range(300):
        response = client.get(url)
        assert response.status_code == 200, response.text
        if response.json()["state"] in states:
            return response.json()
        time.sleep(0.005)
    raise AssertionError("Repair did not complete")


def assessment(client):
    response = client.post(
        "/api/website-assessments", json={"url": "https://www.php.net/"}
    )
    assert response.status_code == 202, response.text
    wait_state(client, response.json()["statusUrl"], {"COMPLETED"})
    return response.json()["assessmentId"]


def connect(client, assessment_id=None):
    response = client.post(
        "/api/repository-connections",
        json={
            "assessmentId": assessment_id or assessment(client),
            "repositoryUrl": "https://github.com/operator/php-site",
            "capabilities": ["homepage"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def prepare(client, connection):
    response = client.post(
        "/api/repository-repairs", json={"connectionId": connection["connectionId"]}
    )
    assert response.status_code == 202, response.text
    return response.json()


def publish(client, repair, key="publish-intent-0001"):
    return client.post(
        f"{repair['statusUrl']}/pull-request", headers={"Idempotency-Key": key}
    )


def test_owned_repair_requires_explicit_publication_and_persists_proof(tmp_path):
    service = RepositoryService(tmp_path / "repository-repairs")
    with repository_client(tmp_path, service) as client:
        assert client.get("/api/repository-connections/status").json() == {
            "available": True,
            "login": "test-operator",
            "message": "Local account available",
        }
        connection = connect(client)
        job = prepare(client, connection)
        ready = wait_state(client, job["statusUrl"], {"READY_TO_PUBLISH"})
        assert service.publish_calls == 0
        assert ready["patch"]["path"] == "php.ini"
        assert {check["phase"] for check in ready["checks"]} == {
            "BASELINE",
            "CANDIDATE",
        }
        assert client.get(
            f"/api/repository-connections?assessmentId={connection['assessmentId']}"
        ).json()["items"] == [connection]
        assert client.get(
            f"/api/repository-repairs?connectionId={connection['connectionId']}&assessmentId={connection['assessmentId']}"
        ).json()["items"] == [ready]
        assert (
            client.get("/api/repository-repairs?connectionId=other").json()["items"]
            == []
        )
        assert publish(client, job).status_code == 202
        published = wait_state(client, job["statusUrl"], {"PUBLISHED"})
        assert published["pullRequest"]["draft"] is True
        assert service.repair_calls == service.publish_calls == 1
        raw_session = client.cookies.get("patchpilot_session")
        saved = list((tmp_path / "repository-repairs").rglob("*.json"))
        assert len(saved) == 2
        assert all(raw_session not in path.read_text() for path in saved)
        client.cookies.clear()
        establish_session(client)
        assert client.get(job["statusUrl"]).status_code == 404
        assert client.get("/api/repository-repairs").json()["items"] == []
        assert client.get("/api/repository-connections").json()["items"] == []
        assert (
            client.post(
                "/api/repository-repairs",
                json={"connectionId": connection["connectionId"]},
            ).status_code
            == 404
        )
        assert publish(client, job).status_code == 404


def test_connection_requires_owned_fresh_complete_assessment_and_selected_checks(
    tmp_path,
):
    service = RepositoryService(tmp_path / "repository-repairs")
    with repository_client(tmp_path, service) as client:
        scan_id = assessment(client)
        payload = {
            "assessmentId": scan_id,
            "repositoryUrl": "https://github.com/operator/php-site",
            "capabilities": ["homepage"],
        }
        assert (
            client.post(
                "/api/repository-connections",
                json=payload,
                headers={"X-CSRF-Token": "wrong"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/repository-connections",
                json=payload,
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )
        for capabilities in (
            ["contact"],
            ["homepage", "homepage"],
            ["homepage", "shell"],
        ):
            assert (
                client.post(
                    "/api/repository-connections",
                    json={**payload, "capabilities": capabilities},
                ).status_code
                == 422
            )
        entry = client.app.state.website_jobs.records[scan_id]
        for state, finished in (
            ("ANALYZING", now()),
            ("FAILED", now()),
            ("COMPLETED", None),
            ("COMPLETED", (datetime.now(UTC) - timedelta(hours=2)).isoformat()),
        ):
            entry.report.state, entry.report.finished_at = state, finished
            assert (
                client.post("/api/repository-connections", json=payload).status_code
                == 409
            )
        entry.report.state, entry.report.finished_at = "COMPLETED", now()
        assert (
            client.post(
                "/api/repository-connections",
                json={**payload, "repositoryUrl": "https://other.example/repo"},
            ).status_code
            == 400
        )
        assert service.connect_calls == 1
        client.cookies.clear()
        establish_session(client)
        assert (
            client.post("/api/repository-connections", json=payload).status_code == 404
        )


def test_durable_progress_excludes_all_other_model_runtime_and_repository_operations(
    tmp_path,
):
    service = RepositoryService(tmp_path / "repository-repairs", gate="repair")
    with repository_client(tmp_path, service) as client:
        connection = connect(client)
        job = prepare(client, connection)
        assert service.entered.wait(2)
        try:
            partial = client.get(job["statusUrl"]).json()
            assert partial["state"] == "BASELINE"
            assert partial["checks"] == service.checkpoint["report"]["checks"]
            assert client.get("/api/health").json()["activeOperation"] == {
                "kind": "repository-repair",
                "id": job["repairId"],
            }
            for url, payload in (
                ("/api/prepare", {}),
                ("/api/resets", {}),
                ("/api/website-assessments", {"url": "https://www.php.net/"}),
                (
                    "/api/repository-repairs",
                    {"connectionId": connection["connectionId"]},
                ),
                (
                    "/api/repository-connections",
                    {
                        "assessmentId": connection["assessmentId"],
                        "repositoryUrl": connection["repositoryUrl"],
                        "capabilities": ["homepage"],
                    },
                ),
            ):
                assert client.post(url, json=payload).status_code == 409
        finally:
            service.allow.set()
        assert wait_state(client, job["statusUrl"], {"READY_TO_PUBLISH"})["patch"]


def test_failed_verification_retains_actual_checks_without_a_publishable_patch(
    tmp_path,
):
    service = RepositoryService(tmp_path / "repository-repairs", repair_failure=True)
    with repository_client(tmp_path, service) as client:
        job = prepare(client, connect(client))
        failed = wait_state(client, job["statusUrl"], {"FAILED"})
        assert failed["checks"][0]["phase"] == "BASELINE"
        assert failed["patch"] is None
        assert failed["proposal"] is None
        assert "PRIVATE_PROVIDER" not in str(failed)
        assert publish(client, job).status_code == 409
        assert service.publish_calls == 0
        assert client.get("/api/health").json()["busy"] is False


def test_publication_replays_inflight_and_completed_intent_without_duplicate_writes(
    tmp_path,
):
    service = RepositoryService(tmp_path / "repository-repairs", gate="publish")
    with repository_client(tmp_path, service) as client:
        job = prepare(client, connect(client))
        wait_state(client, job["statusUrl"], {"READY_TO_PUBLISH"})
        assert client.post(f"{job['statusUrl']}/pull-request").status_code == 422
        assert publish(client, job).status_code == 202
        assert service.entered.wait(2)
        try:
            assert publish(client, job).status_code == 202
            assert publish(client, job, "another-intent-0001").status_code == 409
            assert service.publish_calls == 1
            assert service.checkpoint["report"]["events"][-1]["state"] == "PUBLISHING"
        finally:
            service.allow.set()
        wait_state(client, job["statusUrl"], {"PUBLISHED"})
        assert publish(client, job).status_code == 202
        assert service.publish_calls == 1


def test_unknown_publication_outcome_reconciles_same_job_without_replanning(tmp_path):
    service = RepositoryService(
        tmp_path / "repository-repairs", publication_failure=True
    )
    with repository_client(tmp_path, service) as client:
        job = prepare(client, connect(client))
        ready = wait_state(client, job["statusUrl"], {"READY_TO_PUBLISH"})
        assert publish(client, job).status_code == 202
        failed = wait_state(client, job["statusUrl"], {"FAILED"})
        assert failed["patch"] == ready["patch"]
        assert failed["checks"] == ready["checks"]
        assert "PRIVATE_GITHUB" not in str(failed)
        assert publish(client, job, "new-unrelated-intent").status_code == 409
        assert publish(client, job).status_code == 202
        published = wait_state(client, job["statusUrl"], {"PUBLISHED"})
        assert published["patch"] == ready["patch"]
        assert service.repair_calls == 1
        assert service.publish_calls == 2


def test_publication_key_cannot_be_rebound_to_another_repair(tmp_path):
    service = RepositoryService(tmp_path / "repository-repairs")
    with repository_client(tmp_path, service) as client:
        connection = connect(client)
        first = prepare(client, connection)
        wait_state(client, first["statusUrl"], {"READY_TO_PUBLISH"})
        assert publish(client, first).status_code == 202
        wait_state(client, first["statusUrl"], {"PUBLISHED"})
        second = prepare(client, connection)
        wait_state(client, second["statusUrl"], {"READY_TO_PUBLISH"})
        assert publish(client, second).status_code == 409
        assert service.publish_calls == 1


def test_connection_and_verified_proof_expire_before_new_operations(tmp_path):
    service = RepositoryService(tmp_path / "repository-repairs")
    with repository_client(tmp_path, service) as client:
        connection = connect(client)
        job = prepare(client, connection)
        wait_state(client, job["statusUrl"], {"READY_TO_PUBLISH"})
        manager = client.app.state.repository_jobs
        manager.records[job["repairId"]].ready_at = (
            datetime.now(UTC) - timedelta(hours=2)
        ).isoformat()
        assert publish(client, job).status_code == 409
        manager.connections[connection["connectionId"]].connection.created_at = (
            datetime.now(UTC) - timedelta(hours=2)
        ).isoformat()
        assert (
            client.post(
                "/api/repository-repairs",
                json={"connectionId": connection["connectionId"]},
            ).status_code
            == 409
        )
        assert service.repair_calls == 1
        assert service.publish_calls == 0


def test_repository_operation_quota_is_bounded_with_retry_after(tmp_path):
    service = RepositoryService(tmp_path / "repository-repairs")
    with repository_client(tmp_path, service) as client:
        scan_id = assessment(client)
        for _ in range(5):
            connect(client, scan_id)
        response = client.post(
            "/api/repository-connections",
            json={
                "assessmentId": scan_id,
                "repositoryUrl": "https://github.com/operator/php-site",
                "capabilities": ["homepage"],
            },
        )
        assert response.status_code == 429
        assert 1 <= int(response.headers["retry-after"]) <= 60
        assert service.connect_calls == 5


def test_restart_preserves_publication_intent_and_fails_interrupted_job(tmp_path):
    from patchpilot.backend.repository_jobs import RepositoryJobManager

    service = RepositoryService(tmp_path / "repository-repairs")
    scan = ScanReport(
        assessment_id="website-test",
        url="https://www.php.net/",
        state="COMPLETED",
        created_at=now(),
        finished_at=now(),
    )
    connection = service.connect(
        scan, "https://github.com/operator/php-site", ["homepage"]
    )
    report = RepositoryRepairReport(
        repair_id="repair-interrupted",
        connection_id=connection.connection_id,
        assessment_id=scan.assessment_id,
        repository=connection.repository,
        url=scan.url,
        base_commit=connection.base_commit,
        capabilities=["homepage"],
        created_at=now(),
        state="PUBLISHING",
        patch=RepositoryPatch(
            path="php.ini",
            before_blob_sha="b" * 40,
            after_sha256="c" * 64,
            unified_diff="recorded exact diff",
        ),
    )
    directory = tmp_path / "repository-repairs"
    (directory / "connections").mkdir(parents=True)
    (directory / "reports").mkdir()
    (directory / "connections" / f"{connection.connection_id}.json").write_text(
        StoredConnection(
            owner_hash=RepositoryJobManager.owner("old-session"), connection=connection
        ).model_dump_json(by_alias=True)
    )
    path = directory / "reports" / "repair-interrupted.json"
    path.write_text(
        StoredRepair(
            owner_hash=RepositoryJobManager.owner("old-session"),
            report=report,
            ready_at=now(),
            publication_started_at=now(),
            publication_key_hash="f" * 64,
        ).model_dump_json(by_alias=True)
    )
    with repository_client(tmp_path, service) as client:
        assert client.get("/api/repository-repairs").json()["items"] == []
        assert client.get("/api/health").json()["busy"] is False
    recovered = StoredRepair.model_validate_json(path.read_text())
    assert recovered.report.state == "FAILED"
    assert recovered.report.patch == report.patch
    assert recovered.publication_key_hash == "f" * 64
    assert recovered.publication_started_at
    assert "Retry publication" in recovered.report.error
    assert service.publish_calls == 0


def test_shutdown_drains_offloaded_repair_before_releasing_process_ownership(tmp_path):
    service = RepositoryService(tmp_path / "repository-repairs", gate="repair")
    release = None
    try:
        with repository_client(tmp_path, service) as client:
            prepare(client, connect(client))
            assert service.entered.wait(2)
            release = threading.Timer(0.05, service.allow.set)
            release.start()
        assert service.finished
    finally:
        service.allow.set()
        if release:
            release.join()


def test_baseline_security_findings_and_existing_nondraft_pr_are_reported_truthfully(
    tmp_path,
):
    class BaselineFindingService(RepositoryService):
        def repair(self, *args, **kwargs):
            report = super().repair(*args, **kwargs)
            report.checks.append(
                VerificationCheck(
                    check_id="expose_php",
                    label="Version banner hidden",
                    phase="BASELINE",
                    passed=False,
                    expected="Off",
                    observed="On",
                )
            )
            return report

        def publish(self, *args, **kwargs):
            report = super().publish(*args, **kwargs)
            # An existing draft can have been converted by its owner before reconciliation.
            report.pull_request.draft = False
            return report

    service = BaselineFindingService(tmp_path / "repository-repairs")
    with repository_client(tmp_path, service) as client:
        job = prepare(client, connect(client))
        ready = wait_state(client, job["statusUrl"], {"READY_TO_PUBLISH"})
        assert any(
            not check["passed"]
            for check in ready["checks"]
            if check["phase"] == "BASELINE"
        )
        assert publish(client, job).status_code == 202
        published = wait_state(client, job["statusUrl"], {"PUBLISHED"})
        assert published["pullRequest"]["draft"] is False
        assert published["checks"] == ready["checks"]


def test_durable_published_checkpoint_survives_later_service_cleanup_error(tmp_path):
    class CleanupFailureService(RepositoryService):
        def publish(self, *args, emit, **kwargs):
            report = super().publish(*args, emit=emit, **kwargs)
            emit(report)
            raise RuntimeError("PRIVATE_CLEANUP_DIAGNOSTIC")

    service = CleanupFailureService(tmp_path / "repository-repairs")
    with repository_client(tmp_path, service) as client:
        job = prepare(client, connect(client))
        wait_state(client, job["statusUrl"], {"READY_TO_PUBLISH"})
        assert publish(client, job).status_code == 202
        report = wait_state(client, job["statusUrl"], {"PUBLISHED"})
        assert report["pullRequest"]["number"] == 17
        assert "PRIVATE_CLEANUP" not in str(report)
        assert publish(client, job).status_code == 202
        assert service.publish_calls == 1


def test_default_repository_factory_is_lazy_and_never_uses_a_simulation_fallback(
    tmp_path, monkeypatch
):
    import sys
    from types import ModuleType

    calls = []
    module = ModuleType("patchpilot.repairs.service")

    class UnavailableRepositoryService:
        def __init__(self, *, root):
            calls.append(root)
            raise RuntimeError("PRIVATE_GITHUB_AUTH_CONFIGURATION")

    module.RepositoryRepairService = UnavailableRepositoryService
    monkeypatch.setitem(sys.modules, "patchpilot.repairs.service", module)
    with repository_client(tmp_path, None) as client:
        assert calls == []
        assert client.get("/api/health").json()["websiteAssessmentAvailable"] is True
        response = client.get("/api/repository-connections/status")
        assert response.status_code == 503
        assert "PRIVATE_GITHUB" not in response.text
        assert len(calls) == 1
        assert client.get("/api/repository-connections").json()["items"] == []
        assert client.get("/api/repository-repairs").json()["items"] == []
