"""Typed core boundary; shared/API adapters translate without duplicating decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from patchpilot.core.assessment import Assessment
from patchpilot.core.domain import CheckResult, DeploymentSnapshot, Site
from patchpilot.core.policy import RepairPlan, SecurityPolicy, ValidatedPlan


class RunState(StrEnum):
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


class PlanSource(StrEnum):
    MODEL = "MODEL"
    VERIFIED_RECIPE = "VERIFIED_RECIPE"
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
    SEEDED_DEMO = "SEEDED_DEMO"
    TEST_DOUBLE = "TEST_DOUBLE"


@dataclass(frozen=True)
class Approval:
    approval_id: str
    site_id: str
    policy_revision: str
    assessment_fingerprint: str
    expires_at: datetime
    target_image_alias: str
    allowed_profile_ids: frozenset[str]


@dataclass(frozen=True)
class Candidate:
    handle: str
    snapshot: DeploymentSnapshot


@dataclass(frozen=True)
class ProposedPlan:
    plan: RepairPlan
    source: PlanSource


@dataclass(frozen=True)
class PlanningContext:
    site: Site
    original: DeploymentSnapshot
    assessment: Assessment
    policy: SecurityPolicy


@dataclass(frozen=True)
class RunEvent:
    sequence: int
    run_id: str
    site_id: str
    state: RunState
    attempt: int
    message: str
    approval: Approval
    original: DeploymentSnapshot | None
    candidate: Candidate | None
    plan: ProposedPlan | None
    checks: tuple[CheckResult, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RunResult:
    run_id: str
    site_id: str
    state: RunState
    attempts: int
    plan_source: PlanSource | None
    original: DeploymentSnapshot | None
    final: DeploymentSnapshot | None
    checks: tuple[CheckResult, ...]
    warnings: tuple[str, ...]
    error: str | None
    evidence_complete: bool


class Runtime(Protocol):
    """Operations must honor timeouts; cleanup is scoped to owned staging labels."""

    def inspect(self, site: Site, *, timeout_s: float) -> DeploymentSnapshot: ...

    def stage(
        self,
        site: Site,
        plan: ValidatedPlan,
        run_id: str,
        attempt: int,
        *,
        timeout_s: float,
    ) -> Candidate: ...

    def activate(
        self,
        site: Site,
        candidate: Candidate,
        original: DeploymentSnapshot,
        *,
        timeout_s: float,
    ) -> DeploymentSnapshot: ...

    def restore(
        self,
        site: Site,
        original: DeploymentSnapshot,
        *,
        timeout_s: float,
    ) -> DeploymentSnapshot: ...

    def cleanup(
        self,
        site: Site,
        run_id: str,
        attempt: int,
        *,
        timeout_s: float,
    ) -> None: ...


class Verifier(Protocol):
    def check(
        self,
        site: Site,
        snapshot: DeploymentSnapshot,
        phase: str,
        *,
        timeout_s: float,
    ) -> tuple[CheckResult, ...]: ...


class Planner(Protocol):
    def propose(
        self,
        context: PlanningContext,
        failures: tuple[CheckResult, ...],
        *,
        timeout_s: float,
    ) -> ProposedPlan: ...


class EventSink(Protocol):
    """Return only when the checkpoint has been durably persisted."""

    def emit(self, event: RunEvent) -> None: ...
