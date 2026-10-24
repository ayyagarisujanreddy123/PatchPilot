"""Unit tests for shared data contracts (team-plan.md section 4)."""

import json
import pytest
from pydantic import ValidationError

from patchpilot.shared.contracts import (
    AdvisoryPolicy,
    Approval,
    Assessment,
    AssessmentApprovalItem,
    CandidateSpec,
    CheckPhase,
    CheckResult,
    DeploymentSnapshot,
    PlanSource,
    Recipe,
    RepairPlan,
    RunEvent,
    RunRecord,
    RunState,
    SiteManifest,
)

MOCK_RUN_JSON = """
{
  "schemaVersion": 1,
  "runId": "mock-run-001",
  "siteIds": ["pantry-a"],
  "currentSiteId": "pantry-a",
  "state": "VERIFYING",
  "attempt": 1,
  "planSource": "MODEL",
  "checks": [
    {
      "checkId": "homepage",
      "siteId": "pantry-a",
      "phase": "STAGING",
      "passed": true,
      "message": "Expected organization content received",
      "durationMs": 12
    }
  ],
  "warnings": [],
  "error": null
}
"""


def test_mock_run_validation_and_roundtrip():
    """Verify team-plan.md section 4 illustrative mock JSON validates and round-trips."""
    data = json.loads(MOCK_RUN_JSON)
    record = RunRecord.model_validate(data)

    assert record.schema_version == 1
    assert record.run_id == "mock-run-001"
    assert record.site_ids == ["pantry-a"]
    assert record.current_site_id == "pantry-a"
    assert record.state == RunState.VERIFYING
    assert record.attempt == 1
    assert record.plan_source == PlanSource.MODEL
    assert len(record.checks) == 1
    assert record.checks[0].check_id == "homepage"
    assert record.checks[0].phase == "STAGING"
    assert record.checks[0].passed is True
    assert record.checks[0].duration_ms == 12

    # CamelCase serialization boundary
    dumped = record.model_dump(by_alias=True, exclude_none=True)
    assert dumped["schemaVersion"] == 1
    assert dumped["runId"] == "mock-run-001"
    assert dumped["siteIds"] == ["pantry-a"]
    assert dumped["currentSiteId"] == "pantry-a"
    assert dumped["state"] == "VERIFYING"
    assert dumped["planSource"] == "MODEL"
    assert dumped["checks"][0]["checkId"] == "homepage"
    assert dumped["checks"][0]["durationMs"] == 12


def test_extra_fields_forbidden():
    """Verify unknown fields are rejected at the contract boundary."""
    data = json.loads(MOCK_RUN_JSON)
    data["unknownKey"] = "malicious_or_drifted"

    with pytest.raises(ValidationError):
        RunRecord.model_validate(data)


def test_enum_exact_matching():
    """Verify all 15 states, 5 sources, and 4 check phases match specifications."""
    expected_states = {
        "QUEUED", "ASSESSING", "PLANNING", "STAGING", "VERIFYING",
        "REVISING", "ACTIVATING", "LIVE_VERIFYING", "RESTORING",
        "VERIFIED", "REJECTED", "BLOCKED", "RESTORED",
        "RECOVERY_FAILED", "INTERRUPTED",
    }
    actual_states = {s.value for s in RunState}
    assert actual_states == expected_states
    assert len(RunState) == 15

    expected_sources = {
        "MODEL", "VERIFIED_RECIPE", "DETERMINISTIC_FALLBACK",
        "SEEDED_DEMO", "TEST_DOUBLE",
    }
    actual_sources = {s.value for s in PlanSource}
    assert actual_sources == expected_sources
    assert len(PlanSource) == 5

    expected_phases = {"BASELINE", "STAGING", "LIVE", "RESTORATION"}
    actual_phases = {p.value for p in CheckPhase}
    assert actual_phases == expected_phases
    assert len(CheckPhase) == 4


def test_all_contract_models():
    """Verify instantiating and serializing all shared models."""
    manifest = SiteManifest(
        site_id="pantry-a",
        display_name="Pantry A",
        base_url="http://127.0.0.1:8081",
        capabilities=["homepage", "contact"],
    )
    assert manifest.model_dump(by_alias=True)["siteId"] == "pantry-a"

    policy = AdvisoryPolicy(
        policy_revision="2026-018",
        runtime_branch="php-8.3",
        approved_image_aliases={"php-8.3": "php:8.3.36-apache"},
        approved_profiles=["default"],
        required_mitigations=["session.upload_progress.enabled=0"],
    )
    assert policy.model_dump(by_alias=True)["policyRevision"] == "2026-018"

    assessment = Assessment(
        assessment_id="ass-1",
        site_id="pantry-a",
        fingerprint="fp-123",
        policy_revision="2026-018",
        applicability="VULNERABLE",
        can_repair=True,
    )
    assert assessment.model_dump(by_alias=True)["canRepair"] is True

    approval = Approval(
        approval_id="app-1",
        site_ids=["pantry-a"],
        assessments=[AssessmentApprovalItem(assessment_id="ass-1", fingerprint="fp-123")],
        policy_revision="2026-018",
    )
    assert approval.model_dump(by_alias=True)["approvalId"] == "app-1"

    snapshot = DeploymentSnapshot(
        site_id="pantry-a",
        deployment_id="dep-1",
        endpoint="http://127.0.0.1:8081",
        php_version="8.3.10",
        sapi="apache2handler",
    )
    assert snapshot.model_dump(by_alias=True)["phpVersion"] == "8.3.10"

    plan = RepairPlan(
        target_image_alias="php:8.3.36-apache",
        configuration_profile_id="default",
        rationale="Update runtime to resolve CVEs",
    )
    assert plan.model_dump(by_alias=True)["targetImageAlias"] == "php:8.3.36-apache"

    recipe = Recipe(
        recipe_id="rec-1",
        compatibility_key="comp-key-hash",
        successful_plan=plan,
        originating_run_id="run-1",
        originating_site_id="pantry-a",
        verified_at="2026-10-24T12:00:00Z",
    )
    assert recipe.model_dump(by_alias=True)["compatibilityKey"] == "comp-key-hash"

    event = RunEvent(
        sequence=1,
        timestamp="2026-10-24T12:00:00Z",
        site_id="pantry-a",
        state=RunState.QUEUED,
        message="Queued",
    )
    assert event.model_dump(by_alias=True)["sequence"] == 1
