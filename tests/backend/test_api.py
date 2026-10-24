"""Integration and endpoint tests for FastAPI application and FakeRepairService."""

import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from patchpilot.backend.api import FakeRepairService
from patchpilot.backend.app import create_app
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.contracts import RunState


@pytest.fixture
def client(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    recipes_dir = tmp_path / "recipes"
    r_store = FileRunStore(runs_dir=runs_dir)
    e_sink = FileEventSink(runs_dir=runs_dir)
    rec_store = FileRecipeStore(recipes_dir=recipes_dir)
    rep_service = FakeRepairService(
        run_store=r_store,
        event_sink=e_sink,
        recipe_store=rec_store,
        step_delay=0.001,
    )
    app = create_app(
        custom_run_store=r_store,
        custom_event_sink=e_sink,
        custom_recipe_store=rec_store,
        custom_repair_service=rep_service,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_endpoints_happy_path(client: TestClient):
    """Test standard owner journey: sites -> assessment -> approval -> run -> events -> report -> reset."""
    # 1. GET /
    index_resp = client.get("/")
    assert index_resp.status_code == 200
    assert "PatchPilot" in index_resp.text

    # 2. GET /api/sites
    sites_resp = client.get("/api/sites")
    assert sites_resp.status_code == 200
    sites = sites_resp.json()
    assert len(sites["items"]) == 4
    site_ids = [s["siteId"] for s in sites["items"]]
    assert "pantry-a" in site_ids
    assert "clinic-a" in site_ids

    # 3. POST /api/sites/pantry-a/assessments
    ass_resp = client.post("/api/sites/pantry-a/assessments")
    assert ass_resp.status_code == 200
    ass = ass_resp.json()
    assert ass["siteId"] == "pantry-a"
    assert ass["canRepair"] is True
    assert "assessmentId" in ass
    assert "fingerprint" in ass

    # 4. POST /api/approvals
    app_resp = client.post(
        "/api/approvals",
        json={
            "assessments": [{"assessmentId": ass["assessmentId"], "fingerprint": ass["fingerprint"]}],
            "policyRevision": "2026-018-rev1",
        },
    )
    assert app_resp.status_code == 200
    approval = app_resp.json()
    approval_id = approval["approvalId"]
    assert approval["recoveryAuthority"] is True

    # 5. POST /api/runs (202 Accepted)
    run_resp = client.post(
        "/api/runs",
        json={
            "approvalId": approval_id,
            "memoryEnabled": True,
            "targetOutcome": "success",
        },
    )
    assert run_resp.status_code == 202
    run_data = run_resp.json()
    run_id = run_data["runId"]
    assert run_data["statusUrl"] == f"/api/runs/{run_id}"

    # Poll status until VERIFIED
    final_state = None
    for _ in range(40):
        time.sleep(0.08)
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200
        curr = r.json()["state"]
        if curr == "VERIFIED":
            final_state = curr
            break
    assert final_state == "VERIFIED"

    # 6. GET /api/runs (list)
    runs_list_resp = client.get("/api/runs")
    assert runs_list_resp.status_code == 200
    assert any(item["runId"] == run_id for item in runs_list_resp.json()["items"])

    # 7. GET /api/runs/{runId}/events
    events_resp = client.get(f"/api/runs/{run_id}/events?after=0")
    assert events_resp.status_code == 200
    events_data = events_resp.json()
    items = events_data["items"]
    assert len(items) >= 7
    assert [e["sequence"] for e in items] == list(range(1, len(items) + 1))
    assert events_data["nextSequence"] == items[-1]["sequence"]

    # 8. GET /api/runs/{runId}/report
    report_resp = client.get(f"/api/runs/{run_id}/report")
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert report["runId"] == run_id
    assert report["state"] == "VERIFIED"
    assert "markdown" in report

    # 9. POST & GET /api/resets
    reset_resp = client.post("/api/resets", json={"clearRecipes": True})
    assert reset_resp.status_code == 202
    reset_id = reset_resp.json()["resetId"]

    get_reset = client.get(f"/api/resets/{reset_id}")
    assert get_reset.status_code == 200
    assert get_reset.json()["state"] == "COMPLETED"


def test_error_envelopes(client: TestClient):
    """Verify 404 and 422 error shapes strictly follow {error: {code, message, details}}."""
    # 404 unknown site
    resp_site_404 = client.post("/api/sites/unknown-site-404/assessments")
    assert resp_site_404.status_code == 404
    body = resp_site_404.json()
    assert "error" in body
    assert body["error"]["code"] == "404"
    assert "not a registered target" in body["error"]["message"]

    # 404 unknown run
    resp_run_404 = client.get("/api/runs/non-existent-run-id")
    assert resp_run_404.status_code == 404
    body = resp_run_404.json()
    assert "error" in body
    assert body["error"]["code"] == "404"

    # 404 unknown reset
    resp_reset_404 = client.get("/api/resets/non-existent-reset-id")
    assert resp_reset_404.status_code == 404
    body = resp_reset_404.json()
    assert "error" in body
    assert body["error"]["code"] == "404"

    # 422 malformed request payload
    resp_422 = client.post("/api/approvals", json={"invalidField": 999})
    assert resp_422.status_code == 422
    body = resp_422.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["error"]["details"], list)


def test_fake_service_staging_rejection(client: TestClient):
    """Verify fake service failure branch simulates staging rejection resulting in REJECTED state."""
    app_resp = client.post("/api/approvals", json={"assessments": [], "policyRevision": "rev1"})
    approval_id = app_resp.json()["approvalId"]

    run_resp = client.post(
        "/api/runs",
        json={"approvalId": approval_id, "targetOutcome": "reject_staging"},
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["runId"]

    final_state = None
    for _ in range(40):
        time.sleep(0.08)
        r = client.get(f"/api/runs/{run_id}")
        curr = r.json()["state"]
        if curr in ("REJECTED", "VERIFIED", "RESTORED"):
            final_state = curr
            break

    assert final_state == "REJECTED"

    # Verify event trail
    ev_resp = client.get(f"/api/runs/{run_id}/events?after=0")
    states = [e["state"] for e in ev_resp.json()["items"]]
    assert "REVISING" in states
    assert states[-1] == "REJECTED"


def test_fake_service_activation_restoration(client: TestClient):
    """Verify fake service failure branch simulates live failure resulting in RESTORED state."""
    app_resp = client.post("/api/approvals", json={"assessments": [], "policyRevision": "rev1"})
    approval_id = app_resp.json()["approvalId"]

    run_resp = client.post(
        "/api/runs",
        json={"approvalId": approval_id, "targetOutcome": "restore_activation"},
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["runId"]

    final_state = None
    for _ in range(40):
        time.sleep(0.08)
        r = client.get(f"/api/runs/{run_id}")
        curr = r.json()["state"]
        if curr in ("RESTORED", "VERIFIED", "REJECTED"):
            final_state = curr
            break

    assert final_state == "RESTORED"

    # Verify event trail
    ev_resp = client.get(f"/api/runs/{run_id}/events?after=0")
    states = [e["state"] for e in ev_resp.json()["items"]]
    assert "LIVE_VERIFYING" in states
    assert "RESTORING" in states
    assert states[-1] == "RESTORED"
