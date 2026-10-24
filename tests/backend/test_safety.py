"""Trust and concurrency regressions at the real API boundary."""

from fastapi.testclient import TestClient

from patchpilot.backend.api import FakeRepairService
from patchpilot.backend.app import create_app
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore


def test_session_is_required_before_mutations(tmp_path):
    runs = FileRunStore(tmp_path / "runs")
    events = FileEventSink(tmp_path / "runs")
    recipes = FileRecipeStore(tmp_path / "recipes")
    service = FakeRepairService(runs, events, recipes, step_delay=0.001)
    with TestClient(create_app(runs, events, recipes, service)) as client:
        response = client.post("/api/sites/pantry-a/assessments")
        assert response.status_code == 403
        session = client.get("/api/session")
        assert session.status_code == 200
        assert session.json()["csrfToken"]
        cookie = session.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        headers = {"X-CSRF-Token": session.json()["csrfToken"], "Origin": "http://testserver"}
        assert client.post("/api/sites/pantry-a/assessments", headers=headers).status_code == 200
        unknown = client.post(
            "/api/runs", json={"approvalId": "invented"},
            headers={**headers, "Idempotency-Key": "unknown-approval"},
        )
        assert unknown.status_code == 404
        assert client.get("/api/runs").json()["items"] == []


def test_csrf_and_same_origin_are_both_enforced(client):
    for headers in (
        {"X-CSRF-Token": "wrong"},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Origin": "http://testserver:9000"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        assert client.post("/api/assessments", json={"siteId": "pantry-a"}, headers=headers).status_code == 403
    client.headers.pop("Origin")
    assert client.post("/api/assessments", json={"siteId": "pantry-a"}).status_code == 403
    assert client.post("/api/assessments", json={"siteId": "pantry-a"}, headers={"Referer": "http://testserver/"}).status_code == 200


def test_assessments_and_approvals_belong_to_issuing_session(client):
    item = client.post("/api/assessments", json={"siteId": "clinic-b"}).json()
    body = {"assessments": [{"assessmentId": item["assessmentId"], "fingerprint": item["fingerprint"]}], "policyRevision": item["policyRevision"]}
    approval = client.post("/api/approvals", json=body).json()
    client.cookies.clear()
    csrf = client.get("/api/session").json()["csrfToken"]
    client.headers.update({"X-CSRF-Token": csrf})
    assert client.post("/api/approvals", json=body).status_code == 404
    assert client.post("/api/runs", json={"approvalId": approval["approvalId"]}, headers={"Idempotency-Key": "cross-session"}).status_code == 404
    assert client.get("/api/runs").json()["items"] == []


def test_unknown_fields_and_missing_idempotency_are_rejected(client):
    from tests.backend.test_api import approve

    approval = approve(client)
    assert client.post("/api/runs", json={"approvalId": approval["approvalId"]}).status_code == 400
    assert client.post("/api/runs", json={"approvalId": approval["approvalId"], "overridePolicy": True}, headers={"Idempotency-Key": "unknown-field"}).status_code == 422
    assert client.get("/api/runs").json()["items"] == []


def test_default_composition_is_real_and_rejects_simulation_steering(tmp_path, monkeypatch):
    from patchpilot.core import service as service_module

    class ConfiguredService(FakeRepairService):
        async def health(self):
            return {"mode": "REAL", "ready": True, "prepared": True}

    monkeypatch.setattr(service_module, "RealRepairService", ConfiguredService)
    runs = FileRunStore(tmp_path / "runs")
    events = FileEventSink(tmp_path / "runs")
    recipes = FileRecipeStore(tmp_path / "recipes")
    app = create_app(runs, events, recipes)
    with TestClient(app) as client:
        csrf = client.get("/api/session").json()["csrfToken"]
        client.headers.update({"X-CSRF-Token": csrf, "Origin": "http://testserver"})
        assert isinstance(app.state.repair_service, ConfiguredService)
        assert client.get("/api/health").json()["mode"] == "REAL"
        response = client.post("/api/runs", json={"approvalId": "irrelevant", "targetOutcome": "success"}, headers={"Idempotency-Key": "simulator-is-not-live"})
        assert response.status_code == 400
        assert "simulation" in response.json()["error"]["message"]
        assert client.get("/api/runs").json()["items"] == []


def test_expired_session_is_rejected_and_renewed(client):
    session_id = client.cookies.get("patchpilot_session")
    client.app.state.control.session_expiry[session_id] = 0
    assert client.post("/api/assessments", json={"siteId": "clinic-a"}).status_code == 403
    renewed = client.get("/api/session")
    assert renewed.status_code == 200
    assert client.cookies.get("patchpilot_session") != session_id
    client.headers.update({"X-CSRF-Token": renewed.json()["csrfToken"]})
    assert client.post("/api/assessments", json={"siteId": "clinic-a"}).status_code == 200
