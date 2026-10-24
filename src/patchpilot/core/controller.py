"""Approval-bound repair orchestration; runtime and persistence are injected."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

from patchpilot.core.assessment import assess
from patchpilot.core.domain import (
    CheckResult,
    DeploymentSnapshot,
    Site,
    checks_complete,
)
from patchpilot.core.policy import PolicyError, RepairPlan, SecurityPolicy
from patchpilot.core.ports import (
    Approval,
    Candidate,
    EventSink,
    Planner,
    PlanningContext,
    PlanSource,
    ProposedPlan,
    RunEvent,
    RunResult,
    RunState,
    Runtime,
    Verifier,
)


class _Abort(ValueError):
    """A public, credential-free explanation of a core safety gate."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _local_endpoint(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and (parsed.port is None or 1 <= parsed.port <= 65535)
    )


@dataclass(frozen=True)
class RepairController:
    policy: SecurityPolicy
    runtime: Runtime
    verifier: Verifier
    planner: Planner
    journal: EventSink
    now: Callable[[], datetime] = _utc_now
    monotonic: Callable[[], float] = time.monotonic
    run_timeout_s: float = 600.0

    def run(self, site: Site, approval: Approval, *, run_id: str) -> RunResult:
        return _Execution(self, site, approval, run_id).execute()


class _Execution:
    """Mutable state belongs to one run, never to the reusable service instance."""

    def __init__(
        self,
        service: RepairController,
        site: Site,
        approval: Approval,
        run_id: str,
    ) -> None:
        self.service, self.site, self.approval, self.run_id = (
            service,
            site,
            approval,
            run_id,
        )
        self.state = RunState.QUEUED
        self.attempt = self.sequence = 0
        self.original: DeploymentSnapshot | None = None
        self.final: DeploymentSnapshot | None = None
        self.candidate: Candidate | None = None
        self.proposed: ProposedPlan | None = None
        self.checks: list[CheckResult] = []
        self.warnings: list[str] = []
        self.error: str | None = None
        self.evidence_complete = True
        self.activation_started = False
        self.deadline = service.monotonic() + service.run_timeout_s

    def execute(self) -> RunResult:
        try:
            self._preflight()
            self._repair()
        except Exception as error:
            self.error = self._reason(error)
            self.state = RunState.BLOCKED
        self._emit(self.state, self.error or "Repair verified", required=False)
        return RunResult(
            self.run_id,
            self.site.site_id,
            self.state,
            self.attempt,
            self.proposed.source if self.proposed else None,
            self.original,
            self.final,
            tuple(self.checks),
            tuple(self.warnings),
            self.error,
            self.evidence_complete,
        )

    def _preflight(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", self.run_id):
            raise _Abort("Invalid run identifier")
        if (
            not math.isfinite(self.service.run_timeout_s)
            or self.service.run_timeout_s <= 0
        ):
            raise _Abort("A finite positive run deadline is required")
        if self.site.site_id not in self.service.policy.registered_site_ids:
            raise _Abort("Site is not registered for repair")
        if not _local_endpoint(self.site.base_url):
            raise _Abort("The prototype accepts registered loopback sites only")
        if self.service.policy.max_candidate_attempts not in (1, 2):
            raise _Abort("Candidate attempts must be one or two")
        self._approval_current()

    def _approval_current(self) -> None:
        policy, approval = self.service.policy, self.approval
        now = self.service.now()
        if (
            approval.site_id != self.site.site_id
            or approval.policy_revision != policy.revision
            or approval.target_image_alias != policy.target_image_alias
            or not approval.allowed_profile_ids
            or approval.expires_at.utcoffset() is None
            or now.utcoffset() is None
            or approval.expires_at <= now
        ):
            raise _Abort("Approval is expired or outside the current repair scope")

    def _repair(self) -> None:
        self._emit(RunState.ASSESSING, "Recheck the approved deployment")
        original = self.service.runtime.inspect(self.site, timeout_s=self._budget(15))
        if not isinstance(original, DeploymentSnapshot):
            raise _Abort("Runtime inspection did not return a normalized deployment")
        self.original = original
        if original.base_url != self.site.base_url:
            raise _Abort("Observed deployment address differs from the registered site")
        baseline = self._verify(original, "BASELINE")
        assessment = assess(self.site, original, baseline, self.service.policy)
        if assessment.fingerprint != self.approval.assessment_fingerprint:
            raise _Abort("Deployment or checks changed; a fresh assessment is required")
        if not assessment.can_repair:
            raise _Abort(assessment.blocked_reason or "No supported repair is required")
        context = PlanningContext(self.site, original, assessment, self.service.policy)
        failures: tuple[CheckResult, ...] = ()
        for attempt in range(1, self.service.policy.max_candidate_attempts + 1):
            self.attempt = attempt
            stage_started = False
            try:
                state = RunState.PLANNING if attempt == 1 else RunState.REVISING
                self._emit(state, "Choose an approved repair using available evidence")
                proposed = self.service.planner.propose(
                    context, failures, timeout_s=self._budget(30)
                )
                if (
                    not isinstance(proposed, ProposedPlan)
                    or not isinstance(proposed.plan, RepairPlan)
                    or not isinstance(proposed.source, PlanSource)
                ):
                    raise _Abort(
                        "Planner must return a typed plan and registered source"
                    )
                self.proposed = proposed
                plan = self.service.policy.validate_plan(
                    self.site.site_id, self.proposed.plan
                )
                if plan.profile.profile_id not in self.approval.allowed_profile_ids:
                    raise _Abort(
                        "The configuration profile was not approved by the owner"
                    )
                self.candidate = None
                self._emit(RunState.STAGING, "Prepare an isolated candidate")
                stage_started = True
                candidate = self.service.runtime.stage(
                    self.site, plan, self.run_id, attempt, timeout_s=self._budget(60)
                )
                if not isinstance(candidate, Candidate) or not isinstance(
                    candidate.snapshot, DeploymentSnapshot
                ):
                    raise _Abort(
                        "Runtime staging did not return a normalized candidate"
                    )
                self.candidate = candidate
                self._candidate_bound()
                self._emit(RunState.VERIFYING, "Check candidate security and behavior")
                failures = self._verify(self.candidate.snapshot, "STAGING")
                if not checks_complete(
                    self.site, failures
                ) or not self._security_matches(self.candidate.snapshot):
                    gate = CheckResult(
                        "candidate_gate",
                        False,
                        "Required candidate checks or security policy did not pass",
                        "STAGING",
                        self.site.site_id,
                    )
                    failures = (*failures, gate)
                    self.checks.append(gate)
                    self.state = RunState.REJECTED
                    self.error = (
                        "Candidate verification failed within the attempt limit"
                    )
                    continue
                self._approval_current()
                if (
                    self.service.runtime.inspect(self.site, timeout_s=self._budget(15))
                    != original
                ):
                    raise _Abort(
                        "Original changed during staging; reassessment is required"
                    )
                self._emit(
                    RunState.ACTIVATING, "Retain original and activate tested content"
                )
                self._approval_current()
                activation_timeout = self._budget(30)
                self.activation_started = True
                self.final = self.service.runtime.activate(
                    self.site, self.candidate, original, timeout_s=activation_timeout
                )
                if self.final != replace(
                    self.candidate.snapshot, base_url=self.site.base_url
                ):
                    raise _Abort("Activated content differs from the tested candidate")
                self._emit(
                    RunState.LIVE_VERIFYING, "Repeat checks at the original address"
                )
                live_checks = self._verify(self.final, "LIVE")
                if not checks_complete(
                    self.site, live_checks
                ) or not self._security_matches(self.final):
                    raise _Abort("Live verification failed")
                self.error = None
                self._emit(
                    RunState.VERIFIED, "Live security and application checks passed"
                )
                return
            except Exception as error:
                if self.activation_started:
                    self.error = self._reason(error)
                    self._restore(original)
                    return
                raise
            finally:
                if stage_started:
                    self._cleanup()

    def _candidate_bound(self) -> None:
        assert self.candidate is not None and self.original is not None
        snapshot = self.candidate.snapshot
        if (
            snapshot.site_id != self.site.site_id
            or not _local_endpoint(snapshot.base_url)
            or (urlsplit(snapshot.base_url).port or 80)
            == (urlsplit(self.site.base_url).port or 80)
            or not self.candidate.handle
            or not snapshot.image_id
            or not snapshot.application_hash
            or not snapshot.configuration_hash
            or snapshot.application_hash != self.original.application_hash
            or snapshot.base_image_digest != self.service.policy.image_digest
        ):
            raise _Abort(
                "Candidate is outside the approved site or immutable artifact scope"
            )

    def _security_matches(self, snapshot: DeploymentSnapshot) -> bool:
        return (
            snapshot.php_version == self.service.policy.fixed_version
            and snapshot.sapi == "apache2handler"
            and snapshot.upload_progress_enabled is False
        )

    def _verify(
        self,
        snapshot: DeploymentSnapshot,
        phase: str,
        *,
        recovery: bool = False,
    ) -> tuple[CheckResult, ...]:
        timeout = 45.0 if recovery else self._budget(45)
        checks = tuple(
            replace(check, phase=phase, site_id=self.site.site_id)
            for check in self.service.verifier.check(
                self.site, snapshot, phase, timeout_s=timeout
            )
        )
        self.checks.extend(checks)
        return checks

    def _restore(self, original: DeploymentSnapshot) -> None:
        self._emit(
            RunState.RESTORING,
            "Attempt verified restoration of the original",
            required=False,
        )
        try:
            restored = self.service.runtime.restore(self.site, original, timeout_s=30)
            if restored != original:
                raise _Abort("Restoration identity differs from the retained original")
            checks = self._verify(restored, "RESTORATION", recovery=True)
            if not checks_complete(self.site, checks):
                raise _Abort("Restoration verification failed")
            self.final = restored
            self.state = RunState.RESTORED
        except Exception:
            self.final = None
            self.state = RunState.RECOVERY_FAILED
            self.warnings.append(
                "Original restoration could not be verified; human help is required"
            )

    def _cleanup(self) -> None:
        try:
            self.service.runtime.cleanup(
                self.site, self.run_id, self.attempt, timeout_s=15
            )
        except Exception:
            self.warnings.append(f"Staging cleanup failed for attempt {self.attempt}")

    def _budget(self, maximum: float) -> float:
        remaining = self.deadline - self.service.monotonic()
        if remaining <= 0:
            raise _Abort("Repair deadline expired")
        return min(maximum, remaining)

    def _reason(self, error: Exception) -> str:
        if isinstance(error, (_Abort, PolicyError)):
            return str(error)
        return f"Operation failed during {self.state.value}; see adapter diagnostics"

    def _emit(self, state: RunState, message: str, *, required: bool = True) -> None:
        self.state = state
        self.sequence += 1
        event = RunEvent(
            self.sequence,
            self.run_id,
            self.site.site_id,
            state,
            self.attempt,
            message,
            self.approval,
            self.original,
            self.candidate,
            self.proposed,
            tuple(self.checks),
            tuple(self.warnings),
        )
        try:
            self.service.journal.emit(event)
        except Exception as error:
            self.evidence_complete = False
            self.warnings.append(
                f"Evidence checkpoint could not be persisted: {state.value}"
            )
            if required:
                raise _Abort(
                    "Required evidence checkpoint could not be persisted"
                ) from error
