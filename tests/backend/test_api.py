"""Owner workflow against explicitly simulated execution and real API guards."""

import time

import pytest

def approve(client, site_id="clinic-a"):
    assessment = client.post("/api/assessments", json={"siteId": site_id})
    assert assessment.status_code == 200
    item = assessment.json()
    response = client.post("/api/approvals", json={
        "assessments": [{"assessmentId": item["assessmentId"], "fingerprint": item["fingerprint"]}],
        "policyRevision": item["policyRevision"],
    })
    assert response.status_code == 200
    assert response.json()["siteIds"] == [site_id]
    assert "operatorSession" not in response.json()
    return response.json()


def wait_run(client, run_id):
    for _ in range(200):
        record = client.get(f"/api/runs/{run_id}").json()
        if record["state"] in {"VERIFIED", "REJECTED", "RESTORED", "BLOCKED", "INTERRUPTED", "RECOVERY_FAILED"} and record["evidenceComplete"]:
            return record
        time.sleep(0.005)
    raise AssertionError(f"Run did not finish: {record}")


def test_owner_flow_serves_dashboard_and_preserves_target(client):
    assert '<title>PatchPilot</title>' in client.get("/").text
    assert client.get("/styles.css").status_code == 200
    assert client.get("/js/main.js").status_code == 200
    assert client.get("/static/js/main.js").status_code == 200
    assert client.get("/api/health").json()["mode"] == "SIMULATION"
    assert len(client.get("/api/sites").json()["items"]) == 4
    approval = approve(client)
    response = client.post("/api/runs", json={"approvalId": approval["approvalId"]}, headers={"Idempotency-Key": "owner-flow"})
    assert response.status_code == 202
    run_id = response.json()["runId"]
    record = wait_run(client, run_id)
    assert record["state"] == "VERIFIED"
    assert record["siteIds"] == ["clinic-a"]
    assert record["planSource"] == "TEST_DOUBLE"
    assert any("SIMULATION" in warning for warning in record["warnings"])
    events = client.get(f"/api/runs/{run_id}/events").json()
    assert [event["sequence"] for event in events["items"]] == list(range(1, len(events["items"]) + 1))
    assert events["nextSequence"] == len(events["items"])
    assert all(event["siteId"] in {None, "clinic-a"} for event in events["items"])
    report = client.get(f"/api/runs/{run_id}/report").json()
    assert report["provenance"] == {"source": "TEST_DOUBLE", "simulation": True}
    assert report["securityResults"] == {}
    assert report["changes"] == []


def test_errors_are_structured(client):
    for path in ("/api/runs/unknown", "/api/resets/unknown"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["message"]
    assert client.post("/api/assessments", json={"siteId": "unregistered"}).status_code == 404
    response = client.post("/api/approvals", json={"invalidField": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(response.json()["error"]["details"], list)


@pytest.mark.parametrize("outcome,state", [("reject_staging", "REJECTED"), ("restore_activation", "RESTORED")])
def test_simulated_failure_never_reports_real_security_success(client, outcome, state):
    approval = approve(client, "pantry-a")
    response = client.post("/api/runs", json={"approvalId": approval["approvalId"], "targetOutcome": outcome}, headers={"Idempotency-Key": outcome})
    record = wait_run(client, response.json()["runId"])
    assert record["state"] == state
    report = client.get(response.json()["statusUrl"] + "/report").json()
    assert report["securityResults"] == {}
    assert report["changes"] == []
    if state == "RESTORED":
        assert "unpatched" in record["error"]


def test_multiple_assessments_keep_exact_sites(client):
    items = [client.post(f"/api/sites/{site}/assessments").json() for site in ("clinic-b", "pantry-b")]
    approval = client.post("/api/approvals", json={"assessments": [{"assessmentId": item["assessmentId"], "fingerprint": item["fingerprint"]} for item in items], "policyRevision": items[0]["policyRevision"]})
    assert approval.json()["siteIds"] == ["clinic-b", "pantry-b"]
    run = client.post("/api/runs", json={"approvalId": approval.json()["approvalId"]}, headers={"Idempotency-Key": "fleet-selection"})
    record = wait_run(client, run.json()["runId"])
    assert set(record["siteResults"]) == {"clinic-b", "pantry-b"}
    assert all(result["outcome"] == "VERIFIED" for result in record["siteResults"].values())


def test_forged_assessments_and_changed_policy_are_rejected(client):
    assessment = client.post("/api/assessments", json={"siteId": "clinic-a"}).json()
    body = {"assessments": [{"assessmentId": assessment["assessmentId"], "fingerprint": "forged"}], "policyRevision": assessment["policyRevision"]}
    assert client.post("/api/approvals", json=body).status_code == 400
    body["assessments"][0]["fingerprint"] = assessment["fingerprint"]
    body["policyRevision"] = "forged"
    assert client.post("/api/approvals", json=body).status_code == 400
    assert client.post("/api/approvals", json={"assessments": [], "policyRevision": "simulation-v1"}).status_code == 422
    body["assessments"][0]["assessmentId"] = "unknown"
    assert client.post("/api/approvals", json=body).status_code == 404


def test_prepare_and_reset_have_real_operation_status(client, run_store):
    assert client.post("/api/prepare", json={}).json()["state"] == "COMPLETED"
    assert client.get("/api/health").json()["prepared"] is True
    response = client.post("/api/resets", json={"clearRecipes": True})
    assert response.status_code == 202
    for _ in range(100):
        status = client.get(response.json()["statusUrl"]).json()
        if status["state"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.005)
    assert status["state"] == "COMPLETED"
    assert status["clearedRecipes"] == 0
    assert client.get("/api/health").json()["busy"] is False
