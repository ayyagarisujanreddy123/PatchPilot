"""Shared data contracts matching team-plan.md section 4.

Rules:
- Python properties use snake_case.
- JSON boundary uses camelCase aliases.
- State and source values use uppercase enums.
- Unknown fields are strictly rejected (extra="forbid").
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class RunState(str, Enum):
    QUEUED = "QUEUED"
    ASSESSING = "ASSESSING"
    PLANNING = "PLANNING"
    STAGING = "STAGING"
    VERIFYING = "VERIFYING"
    REVISING = "REVISING"
    ACTIVATING = "ACTIVATING"
    LIVE_VERIFYING = "LIVE_VERIFYING"
    RESTORING = "RESTORING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    RESTORED = "RESTORED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    INTERRUPTED = "INTERRUPTED"


class PlanSource(str, Enum):
    MODEL = "MODEL"
    VERIFIED_RECIPE = "VERIFIED_RECIPE"
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
    SEEDED_DEMO = "SEEDED_DEMO"
    TEST_DOUBLE = "TEST_DOUBLE"


class CheckPhase(str, Enum):
    BASELINE = "BASELINE"
    STAGING = "STAGING"
    LIVE = "LIVE"
    RESTORATION = "RESTORATION"


class ContractModel(BaseModel):
    """Base model enforcing camelCase serialization and forbidding unknown fields."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class CheckResult(ContractModel):
    check_id: str
    site_id: Optional[str] = None
    phase: str
    passed: bool
    message: str
    duration_ms: Optional[int] = None
    expected_value: Optional[Any] = None
    observed_value: Optional[Any] = None
    structured_failure: Optional[dict[str, Any]] = None


class SiteManifest(ContractModel):
    site_id: str
    display_name: str
    base_url: str
    capabilities: list[str] = Field(default_factory=list)
    assessment_state: Optional[str] = None
    last_run_id: Optional[str] = None
    local_address: Optional[str] = None
    template_revision: Optional[str] = None
    expected_content: Optional[str] = None
    launch_settings: Optional[dict[str, Any]] = None
    ownership_labels: Optional[dict[str, str]] = None


class AdvisoryPolicy(ContractModel):
    policy_revision: str
    runtime_branch: str
    approved_image_aliases: dict[str, str] = Field(default_factory=dict)
    approved_profiles: list[str] = Field(default_factory=list)
    required_mitigations: list[str] = Field(default_factory=list)
    deadlines: Optional[dict[str, int]] = None


class Assessment(ContractModel):
    assessment_id: str
    site_id: str
    fingerprint: str
    policy_revision: str
    applicability: str
    current_runtime: dict[str, Any] = Field(default_factory=dict)
    proposed_changes: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    can_repair: bool
    blocked_reason: Optional[str] = None


class AssessmentApprovalItem(ContractModel):
    assessment_id: str
    fingerprint: str


class Approval(ContractModel):
    approval_id: str
    site_ids: list[str] = Field(default_factory=list)
    assessments: list[AssessmentApprovalItem] = Field(default_factory=list)
    policy_revision: str
    expires_at: Optional[str] = None
    operator_session: Optional[str] = None
    permitted_changes: list[str] = Field(default_factory=list)
    recovery_authority: bool = True


class RepairPlan(ContractModel):
    target_image_alias: str
    configuration_profile_id: str
    rationale: str


class CandidateSpec(ContractModel):
    candidate_endpoint: str
    derived_image_id: str
    application_hash: str
    configuration_hash: str
    deployment_id: str
    expected_behavior: list[str] = Field(default_factory=list)
    resource_handle: Optional[str] = None


class DeploymentSnapshot(ContractModel):
    site_id: str
    deployment_id: str
    endpoint: str
    php_version: Optional[str] = None
    sapi: Optional[str] = None
    upload_progress: Optional[str] = None
    container_id: Optional[str] = None
    labels: Optional[dict[str, str]] = None


class Recipe(ContractModel):
    recipe_id: str
    compatibility_key: str
    successful_plan: RepairPlan
    originating_run_id: str
    originating_site_id: str
    failed_check_observations: list[CheckResult] = Field(default_factory=list)
    verification_evidence: dict[str, Any] = Field(default_factory=dict)
    verified_at: str


class RunEvent(ContractModel):
    sequence: int
    timestamp: str
    site_id: Optional[str] = None
    state: RunState
    message: str
    check: Optional[CheckResult] = None


class RunRecord(ContractModel):
    schema_version: int = 1
    run_id: str
    site_ids: list[str] = Field(default_factory=list)
    current_site_id: Optional[str] = None
    state: RunState = RunState.QUEUED
    attempt: int = 1
    plan_source: Optional[PlanSource] = None
    checks: list[CheckResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    approval_id: Optional[str] = None
    original_identity: Optional[dict[str, Any]] = None
    candidate_identity: Optional[dict[str, Any]] = None
    candidate_spec: Optional[CandidateSpec] = None
    site_results: Optional[dict[str, Any]] = None
    changes: Optional[list[str]] = None
    security_results: Optional[dict[str, Any]] = None
    recovery: Optional[dict[str, Any]] = None
    provenance: Optional[dict[str, Any]] = None
    durations: Optional[dict[str, int]] = None
    cleanup_result: Optional[dict[str, Any]] = None
    checkpoint: Optional[dict[str, Any]] = None
    evidence_complete: bool = False
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
