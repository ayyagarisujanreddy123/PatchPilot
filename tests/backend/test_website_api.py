"""Website assessment jobs use real admission/persistence with injected agents."""

import json
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from patchpilot.backend.app import create_app
from patchpilot.backend.fake import FakeRepairService
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.webscan.models import ScanReport


def now():
    return datetime.now(UTC).isoformat()


class CompletingAgent:
    calls = 0

    def run(self, url, *, assessment_id, emit):
        self.calls += 1
        report = ScanReport(
            assessment_id=assessment_id,
            url=url,
            created_at=now(),
            state="COLLECTING",
            stage_message="Collecting fresh responses",
        )
        emit(report)
        report.state = "COMPLETED"
        report.finished_at = now()
        report.stage_message = "Fresh assessment complete"
        return report


@contextmanager
def website_client(tmp_path, agent):
    runs = FileRunStore(tmp_path / "runs")
    events = FileEventSink(tmp_path / "runs")
    recipes = FileRecipeStore(tmp_path / "recipes")
    repair = FakeRepairService(runs, events, recipes, step_delay=0.001)
    app = create_app(runs, events, recipes, repair, custom_website_agent=agent)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["csrfToken"]
        client.headers.update({"X-CSRF-Token": token, "Origin": "http://testserver"})
        yield client


def wait_report(client, status_url):
    for _ in range(200):
        report = client.get(status_url)
        assert report.status_code == 200
        if report.json()["state"] in {"COMPLETED", "FAILED"}:
            return report.json()
        time.sleep(0.005)
    raise AssertionError("Website assessment did not reach a terminal state")


def test_website_job_is_persisted_and_owned_by_operator_session(tmp_path):
    agent = CompletingAgent()
    with website_client(tmp_path, agent) as client:
        health = client.get("/api/health").json()
        assert health["websiteAssessmentAvailable"] is True
        assert health["dockerAvailable"] is False
        response = client.post(
            "/api/website-assessments", json={"url": "https://www.php.net/"}
        )
        assert response.status_code == 202
        report = wait_report(client, response.json()["statusUrl"])
        assert report["state"] == "COMPLETED"
        assert report["assessmentId"] == response.json()["assessmentId"]
        assert report["analysis"] is None
        assert report["findings"] == []
        assert agent.calls == 1
        assert client.get("/api/website-assessments").json()["items"][0] == report
        files = list((tmp_path / "website-assessments").glob("*.json"))
        assert len(files) == 1
        assert client.cookies.get("patchpilot_session") not in files[0].read_text()
        client.cookies.clear()
        token = client.get("/api/session").json()["csrfToken"]
        client.headers.update({"X-CSRF-Token": token})
        assert client.get(response.json()["statusUrl"]).status_code == 404
        assert client.get("/api/website-assessments").json()["items"] == []


class ProgressGateAgent:
    def __init__(self, directory, *, crash=False):
        self.directory = directory
        self.crash = crash
        self.entered = threading.Event()
        self.allow = threading.Event()
        self.checkpoint = None

    def run(self, url, *, assessment_id, emit):
        import json

        from patchpilot.webscan.models import Evidence, ResponseSummary

        report = ScanReport(
            assessment_id=assessment_id, url=url, created_at=now(), state="COLLECTING"
        )
        emit(report)
        report.state = "ANALYZING"
        report.stage_message = "Analyzing newly collected observations"
        report.responses = [
            ResponseSummary(
                url=url,
                status=200,
                elapsed_ms=10,
                body_sha256="a" * 64,
                bytes_read=42,
                truncated=False,
            )
        ]
        report.evidence = [
            Evidence(
                evidence_id="e-1",
                url=url,
                kind="header",
                label="Observed server header",
                observed="Injected test observation",
                collected_at=now(),
            )
        ]
        emit(report)
        self.checkpoint = json.loads(
            (self.directory / f"{assessment_id}.json").read_text()
        )
        self.entered.set()
        if not self.allow.wait(timeout=5):
            raise RuntimeError("Test gate timed out")
        if self.crash:
            raise RuntimeError("API_KEY=DO_NOT_EXPOSE_THIS")
        report.state, report.finished_at = "COMPLETED", now()
        return report


def test_progress_is_durable_and_all_operations_share_one_reservation(tmp_path):
    agent = ProgressGateAgent(tmp_path / "website-assessments")
    with website_client(tmp_path, agent) as client:
        created = client.post(
            "/api/website-assessments", json={"url": "https://www.php.net/"}
        )
        assert created.status_code == 202
        assert agent.entered.wait(2)
        try:
            partial = client.get(created.json()["statusUrl"]).json()
            assert partial["state"] == "ANALYZING"
            assert partial["responses"][0]["bytesRead"] == 42
            assert agent.checkpoint["report"]["state"] == "ANALYZING"
            assert agent.checkpoint["report"]["evidence"] == partial["evidence"]
            assert client.get("/api/health").json()["activeOperation"] == {
                "kind": "website-assessment",
                "id": created.json()["assessmentId"],
            }
            assert (
                client.post(
                    "/api/website-assessments",
                    json={"url": "http://php.testsparker.com/"},
                ).status_code
                == 409
            )
            assert client.post("/api/prepare", json={}).status_code == 409
            assert client.post("/api/resets", json={}).status_code == 409
        finally:
            agent.allow.set()
        assert wait_report(client, created.json()["statusUrl"])["state"] == "COMPLETED"


def test_provider_exception_retains_fresh_observations_without_inventing_analysis(
    tmp_path,
):
    agent = ProgressGateAgent(tmp_path / "website-assessments", crash=True)
    with website_client(tmp_path, agent) as client:
        created = client.post(
            "/api/website-assessments", json={"url": "http://php.testsparker.com/"}
        )
        assert agent.entered.wait(2)
        agent.allow.set()
        report = wait_report(client, created.json()["statusUrl"])
        assert report["state"] == "FAILED"
        assert report["analysis"] is None
        assert report["findings"] == []
        assert len(report["responses"]) == 1
        assert report["evidence"][0]["observed"] == "Injected test observation"
        assert report["events"][-1]["stage"] == "FAILED"
        assert "DO_NOT_EXPOSE" not in str(report)
        assert report["finishedAt"]
        assert client.get("/api/health").json()["busy"] is False


def test_url_and_csrf_guards_run_before_the_agent(tmp_path):
    agent = CompletingAgent()
    with website_client(tmp_path, agent) as client:
        for url in (
            "file:///etc/passwd",
            "ftp://example.com/",
            "http://localhost/",
            "http://127.0.0.1/",
            "http://[::1]/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "https://example.com:444/",
            "https://user:secret@example.com/",
            "https://example.com/?token=secret",
        ):
            response = client.post("/api/website-assessments", json={"url": url})
            assert response.status_code == 400, (url, response.text)
        assert (
            client.post(
                "/api/website-assessments",
                json={"url": "https://www.php.net/"},
                headers={"X-CSRF-Token": "wrong"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/website-assessments",
                json={"url": "https://www.php.net/"},
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/website-assessments",
                json={"url": "https://www.php.net/", "inventFindings": True},
            ).status_code
            == 422
        )
        client.cookies.clear()
        assert client.get("/api/website-assessments").status_code == 403
        assert (
            client.post(
                "/api/website-assessments", json={"url": "https://www.php.net/"}
            ).status_code
            == 403
        )
        assert agent.calls == 0
        assert not list((tmp_path / "website-assessments").glob("*.json"))


def test_examples_are_metadata_and_do_not_start_collection(tmp_path):
    agent = CompletingAgent()
    with website_client(tmp_path, agent) as client:
        response = client.get("/api/website-assessments/examples")
        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["url"] for item in items] == [
            "http://php.testsparker.com/",
            "https://www.php.net/",
            "https://demo.phpipam.net/",
        ]
        example = items[0]
        assert example["url"] == "http://php.testsparker.com/"
        assert example["sourceUrl"].startswith("https://www.invicti.com/")
        for item in items:
            assert item["kind"] == "assessment only"
            assert item["connectionSupport"] == "ASSESSMENT_ONLY"
            assert "repositoryUrl" not in item
            assert not ({"findings", "phpVersion", "evidence", "analysis"} & set(item))
        assert agent.calls == 0
        assert client.get("/api/website-assessments").json()["items"] == []


def test_configured_connected_example_is_appended_without_replacing_public_examples(
    tmp_path,
):
    directory = tmp_path / "connected-demo"
    directory.mkdir()
    (directory / "public.json").write_text(
        json.dumps(
            {
                "url": "https://owned-demo.example/",
                "repositoryUrl": "https://github.com/operator/patchpilot-connected-demo",
            }
        )
    )
    agent = CompletingAgent()
    with website_client(tmp_path, agent) as client:
        items = client.get("/api/website-assessments/examples").json()["items"]
        assert len(items) == 4
        connected = items[0]
        assert connected["id"] == "connected-php-demo"
        assert connected["url"] == "https://owned-demo.example/"
        assert connected["kind"] == "connected repair demo"
        assert connected["connectionSupport"] == "CONNECTED"
        assert (
            connected["repositoryUrl"]
            == "https://github.com/operator/patchpilot-connected-demo"
        )
        assert "matching deployment marker" in connected["description"]
        assert all(item["connectionSupport"] == "ASSESSMENT_ONLY" for item in items[1:])
        assert not ({"findings", "phpVersion", "evidence", "analysis"} & set(connected))
        assert agent.calls == 0
        assert not list((tmp_path / "website-assessments").glob("*.json"))
        assert not list((tmp_path / "repository-repairs").rglob("*.json"))


def test_connected_catalog_can_list_multiple_valid_owned_demos_and_ignores_invalid_entries(
    tmp_path,
):
    directory = tmp_path / "connected-demo"
    directory.mkdir()
    first = {
        "url": "https://first-demo.example/",
        "repositoryUrl": "https://github.com/operator/first-demo",
    }
    second = {
        "url": "https://second-demo.example/",
        "repositoryUrl": "https://github.com/operator/second-demo.git",
    }
    (directory / "public.json").write_text(
        json.dumps(
            {
                "items": [
                    first,
                    {
                        "url": "http://127.0.0.1/",
                        "repositoryUrl": first["repositoryUrl"],
                    },
                    second,
                    first,
                ]
            }
        )
    )
    with website_client(tmp_path, CompletingAgent()) as client:
        items = client.get("/api/website-assessments/examples").json()["items"]
        owned = [item for item in items if item["connectionSupport"] == "CONNECTED"]
        assert [item["url"] for item in owned] == [first["url"], second["url"]]
        assert owned[1]["repositoryUrl"] == "https://github.com/operator/second-demo"
        assert len({item["id"] for item in items}) == 5
        assert len(items) == 5


def test_invalid_or_secret_bearing_demo_metadata_keeps_the_public_catalog(tmp_path):
    directory = tmp_path / "connected-demo"
    directory.mkdir()
    path = directory / "public.json"
    repository = "https://github.com/operator/patchpilot-connected-demo"
    invalid = [
        None,
        [],
        {"url": "https://demo.example/"},
        {"url": 123, "repositoryUrl": repository},
        {"url": "http://localhost/", "repositoryUrl": repository},
        {"url": "http://10.0.0.1/", "repositoryUrl": repository},
        {"url": "http://[::1]/", "repositoryUrl": repository},
        {"url": "https://user:PRIVATE@demo.example/", "repositoryUrl": repository},
        {"url": "https://demo.example/?token=PRIVATE", "repositoryUrl": repository},
        {"url": "https://demo.example/#PRIVATE", "repositoryUrl": repository},
        {"url": "https://demo.example/account", "repositoryUrl": repository},
        {
            "url": "https://demo.example/",
            "repositoryUrl": "https://github.com.attacker.example/operator/demo",
        },
        {
            "url": "https://demo.example/",
            "repositoryUrl": "https://PRIVATE@github.com/operator/demo",
        },
        {
            "url": "https://demo.example/",
            "repositoryUrl": f"{repository}?token=PRIVATE",
        },
        {
            "url": "https://demo.example/",
            "repositoryUrl": repository,
            "findings": ["PRIVATE"],
        },
        {"items": [{"url": "https://demo.example/", "repositoryUrl": repository}] * 6},
    ]
    agent = CompletingAgent()
    with website_client(tmp_path, agent) as client:
        for metadata in invalid:
            path.write_text(json.dumps(metadata))
            response = client.get("/api/website-assessments/examples")
            assert response.status_code == 200
            assert len(response.json()["items"]) == 3
            assert all(
                item["connectionSupport"] == "ASSESSMENT_ONLY"
                for item in response.json()["items"]
            )
            assert "PRIVATE" not in response.text
        path.write_text("{not valid JSON")
        assert len(client.get("/api/website-assessments/examples").json()["items"]) == 3
        path.write_bytes(b"x" * (16 * 1024 + 1))
        assert len(client.get("/api/website-assessments/examples").json()["items"]) == 3
        assert agent.calls == 0


def test_connected_catalog_ignores_symlinks_and_nonregular_metadata_without_blocking(
    tmp_path,
):
    import os

    directory = tmp_path / "connected-demo"
    directory.mkdir()
    target = tmp_path / "not-public-metadata.json"
    target.write_text(
        json.dumps(
            {
                "url": "https://demo.example/",
                "repositoryUrl": "https://github.com/operator/demo",
            }
        )
    )
    path = directory / "public.json"
    path.symlink_to(target)
    with website_client(tmp_path, CompletingAgent()) as client:
        assert len(client.get("/api/website-assessments/examples").json()["items"]) == 3
        path.unlink()
        os.mkfifo(path)
        assert len(client.get("/api/website-assessments/examples").json()["items"]) == 3


def test_rate_limit_has_retry_after_and_does_not_call_provider(tmp_path):
    agent = CompletingAgent()
    with website_client(tmp_path, agent) as client:
        for _ in range(5):
            response = client.post(
                "/api/website-assessments", json={"url": "https://www.php.net/"}
            )
            assert response.status_code == 202
            wait_report(client, response.json()["statusUrl"])
        response = client.post(
            "/api/website-assessments", json={"url": "https://www.php.net/"}
        )
        assert response.status_code == 429
        assert 1 <= int(response.headers["retry-after"]) <= 60
        assert agent.calls == 5


def test_shutdown_drains_active_website_job(tmp_path):
    class SlowAgent(CompletingAgent):
        finished = False

        def run(self, *args, **kwargs):
            time.sleep(0.04)
            result = super().run(*args, **kwargs)
            self.finished = True
            return result

    agent = SlowAgent()
    with website_client(tmp_path, agent) as client:
        assert (
            client.post(
                "/api/website-assessments", json={"url": "https://www.php.net/"}
            ).status_code
            == 202
        )
    assert agent.finished


def test_restart_marks_partial_report_failed_without_fabricated_results(tmp_path):
    from patchpilot.backend.website_jobs import StoredAssessment
    from patchpilot.webscan.models import Evidence

    directory = tmp_path / "website-assessments"
    directory.mkdir()
    record = ScanReport(
        assessment_id="website-interrupted",
        url="https://www.php.net/",
        created_at=now(),
        state="ANALYZING",
        evidence=[
            Evidence(
                evidence_id="observed",
                url="https://www.php.net/",
                kind="header",
                label="Recorded header",
                observed="Test observation",
                collected_at=now(),
            )
        ],
    )
    path = directory / "website-interrupted.json"
    path.write_text(
        StoredAssessment(owner_hash="a" * 64, report=record).model_dump_json(
            by_alias=True
        )
    )
    with website_client(tmp_path, CompletingAgent()) as client:
        assert client.get("/api/website-assessments").json()["items"] == []
    recovered = StoredAssessment.model_validate_json(path.read_text()).report
    assert recovered.state == "FAILED"
    assert recovered.analysis is None
    assert recovered.evidence == record.evidence
    assert recovered.findings == []
    assert "Controller stopped" in recovered.error


def test_default_agent_factory_failure_is_reported_without_mock_fallback(
    tmp_path, monkeypatch
):
    import patchpilot.webscan.agent as agent_module

    class MissingConfiguration:
        def __init__(self, **kwargs):
            raise RuntimeError("PROVIDER_KEY_MUST_REMAIN_PRIVATE")

    monkeypatch.setattr(agent_module, "WebsiteAssessmentAgent", MissingConfiguration)
    runs, events, recipes = (
        FileRunStore(tmp_path / "runs"),
        FileEventSink(tmp_path / "runs"),
        FileRecipeStore(tmp_path / "recipes"),
    )
    repair = FakeRepairService(runs, events, recipes)
    with TestClient(create_app(runs, events, recipes, repair)) as client:
        token = client.get("/api/session").json()["csrfToken"]
        client.headers.update({"X-CSRF-Token": token, "Origin": "http://testserver"})
        response = client.post(
            "/api/website-assessments", json={"url": "http://php.testsparker.com/"}
        )
        report = wait_report(client, response.json()["statusUrl"])
        assert report["state"] == "FAILED"
        assert report["responses"] == []
        assert report["analysis"] is None
        assert report["findings"] == []
        assert "PROVIDER_KEY" not in str(report)


async def test_shutdown_rejects_admission_that_was_waiting_for_control_lock(tmp_path):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from patchpilot.backend.control import OperationControl
    from patchpilot.backend.website_jobs import WebsiteJobManager

    control = OperationControl(tmp_path / "runs")
    await control.open()
    agent = CompletingAgent()
    manager = WebsiteJobManager(
        tmp_path / "website-assessments", control, lambda: agent
    )
    try:
        async with control.lock:
            pending = asyncio.create_task(
                manager.submit("https://www.php.net/", "session")
            )
            await asyncio.sleep(0)
            manager.closing = True
        with pytest.raises(HTTPException) as raised:
            await pending
        assert raised.value.status_code == 503
        assert agent.calls == 0
    finally:
        await manager.shutdown()
        control.close()
