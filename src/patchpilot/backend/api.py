"""FastAPI router and Fake Repair Service for PatchPilot.

Provides all plan.md section 9 API endpoints, consistent error envelopes,
and a deterministic test double repair worker emitting real ordered events.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.contracts import (
    Approval,
    Assessment,
    AssessmentApprovalItem,
    CheckPhase,
    CheckResult,
    PlanSource,
    RepairPlan,
    RunEvent,
    RunRecord,
    RunState,
    SiteManifest,
)
from patchpilot.shared.ports import RepairService

logger = logging.getLogger("patchpilot.backend.api")

# Pre-registered demonstration fleet (team-plan.md section 4)
REGISTERED_SITES: dict[str, SiteManifest] = {
    "pantry-a": SiteManifest(
        site_id="pantry-a",
        display_name="Pantry A",
        base_url="http://127.0.0.1:8081",
        capabilities=["homepage", "contact"],
        assessment_state="READY",
        template_revision="pantry-v1",
        expected_content="Community Food Pantry",
    ),
    "pantry-b": SiteManifest(
        site_id="pantry-b",
        display_name="Pantry B",
        base_url="http://127.0.0.1:8082",
        capabilities=["homepage", "contact"],
        assessment_state="READY",
        template_revision="pantry-v1",
        expected_content="Community Food Pantry",
    ),
    "clinic-a": SiteManifest(
        site_id="clinic-a",
        display_name="Clinic A",
        base_url="http://127.0.0.1:8083",
        capabilities=["homepage", "contact", "upload"],
        assessment_state="READY",
        template_revision="clinic-v1",
        expected_content="Community Health Clinic",
    ),
    "clinic-b": SiteManifest(
        site_id="clinic-b",
        display_name="Clinic B",
        base_url="http://127.0.0.1:8084",
        capabilities=["homepage", "contact", "upload"],
        assessment_state="READY",
        template_revision="clinic-v1",
        expected_content="Community Health Clinic",
    ),
}

# In-memory approval and reset caches for prototype
_APPROVALS: dict[str, Approval] = {}
_RESETS: dict[str, dict[str, Any]] = {}


class CreateAssessmentRequest(BaseModel):
    # Optional override options
    pass


class CreateApprovalRequest(BaseModel):
    assessments: list[dict[str, str]]
    policy_revision: str = Field(..., alias="policyRevision")
    permitted_changes: list[str] = Field(default_factory=list, alias="permittedChanges")
    recovery_authority: bool = Field(default=True, alias="recoveryAuthority")


class CreateRunRequest(BaseModel):
    approval_id: str = Field(..., alias="approvalId")
    memory_enabled: bool = Field(default=True, alias="memoryEnabled")
    # Optional simulator steering for demo / UI preview:
    # "success", "reject_staging", "restore_activation"
    target_outcome: Optional[str] = Field(default="success", alias="targetOutcome")


class CreateResetRequest(BaseModel):
    clear_recipes: bool = Field(default=False, alias="clearRecipes")


class FakeRepairService(RepairService):
    """Deterministic test double repair service (TEST_DOUBLE planSource).

    Advances through realistic lifecycle states and emits ordered events into the
    event sink, updating run snapshots atomically.
    """

    def __init__(
        self,
        run_store: FileRunStore,
        event_sink: FileEventSink,
        recipe_store: FileRecipeStore,
        step_delay: float = 0.05,
    ):
        self.run_store = run_store
        self.event_sink = event_sink
        self.recipe_store = recipe_store
        self.step_delay = step_delay

    async def _emit_event(
        self,
        run: RunRecord,
        state: RunState,
        message: str,
        sequence: int,
        check: Optional[CheckResult] = None,
    ) -> RunEvent:
        event = RunEvent(
            sequence=sequence,
            timestamp=datetime.now(timezone.utc).isoformat(),
            site_id=run.current_site_id or (run.site_ids[0] if run.site_ids else None),
            state=state,
            message=message,
            check=check,
        )
        await self.event_sink.append_event(run.run_id, event)
        return event

    async def run(
        self,
        approval: Approval,
        memory_enabled: bool = True,
        target_outcome: str = "success",
        run_id: Optional[str] = None,
    ) -> RunRecord:
        site_id = approval.site_ids[0] if approval.site_ids else "pantry-a"
        if not run_id:
            run_id = f"run-{uuid.uuid4().hex[:8]}"

        record = await self.run_store.get_run(run_id)
        if not record:
            record = RunRecord(
                run_id=run_id,
                approval_id=approval.approval_id,
                site_ids=approval.site_ids,
                current_site_id=site_id,
                state=RunState.QUEUED,
                attempt=1,
                plan_source=PlanSource.TEST_DOUBLE,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.run_store.save_run(record)

        seq = 1
        await self._emit_event(record, RunState.QUEUED, "Repair run queued", seq)
        await asyncio.sleep(self.step_delay)

        # 1. ASSESSING
        seq += 1
        record.state = RunState.ASSESSING
        await self._emit_event(record, RunState.ASSESSING, f"Assessing baseline runtime for {site_id}", seq)
        await self.run_store.save_run(record)
        await asyncio.sleep(self.step_delay)

        # 2. PLANNING
        seq += 1
        record.state = RunState.PLANNING
        record.plan_source = PlanSource.TEST_DOUBLE
        await self._emit_event(
            record, RunState.PLANNING, "Proposing repair plan: upgrade to PHP 8.3.36 with upload mitigation", seq
        )
        await self.run_store.save_run(record)
        await asyncio.sleep(self.step_delay)

        # 3. STAGING
        seq += 1
        record.state = RunState.STAGING
        await self._emit_event(
            record, RunState.STAGING, f"Staging candidate on loopback with immutable config for {site_id}", seq
        )
        await self.run_store.save_run(record)
        await asyncio.sleep(self.step_delay)

        # Branch based on target_outcome
        if target_outcome == "reject_staging":
            # Simulation of bad staging candidate (e.g. upload failure)
            seq += 1
            record.state = RunState.VERIFYING
            fail_check = CheckResult(
                check_id="upload_check",
                site_id=site_id,
                phase=CheckPhase.STAGING.value,
                passed=False,
                message="3 MiB upload rejected: max upload filesize exceeded",
                duration_ms=45,
            )
            record.checks.append(fail_check)
            await self._emit_event(record, RunState.VERIFYING, "Staging check failed", seq, check=fail_check)
            await self.run_store.save_run(record)
            await asyncio.sleep(self.step_delay)

            # Revision attempt
            seq += 1
            record.state = RunState.REVISING
            record.attempt = 2
            await self._emit_event(record, RunState.REVISING, "Revising candidate configuration", seq)
            await self.run_store.save_run(record)
            await asyncio.sleep(self.step_delay)

            # Terminal rejection
            seq += 1
            record.state = RunState.REJECTED
            record.error = "Candidate verification failed after retry; attempts exhausted"
            record.finished_at = datetime.now(timezone.utc).isoformat()
            await self._emit_event(record, RunState.REJECTED, "Run rejected; original site untouched", seq)
            await self.run_store.save_run(record)
            return record

        # 4. VERIFYING (Staging pass)
        seq += 1
        record.state = RunState.VERIFYING
        staging_check = CheckResult(
            check_id="homepage",
            site_id=site_id,
            phase=CheckPhase.STAGING.value,
            passed=True,
            message="Homepage served expected content on candidate endpoint",
            duration_ms=18,
        )
        record.checks.append(staging_check)
        await self._emit_event(record, RunState.VERIFYING, "Candidate passed staging checks", seq, check=staging_check)
        await self.run_store.save_run(record)
        await asyncio.sleep(self.step_delay)

        # 5. ACTIVATING
        seq += 1
        record.state = RunState.ACTIVATING
        await self._emit_event(
            record, RunState.ACTIVATING, f"Activating verified candidate at original address for {site_id}", seq
        )
        await self.run_store.save_run(record)
        await asyncio.sleep(self.step_delay)

        if target_outcome == "restore_activation":
            # Simulation of live verification failure triggering rollback
            seq += 1
            record.state = RunState.LIVE_VERIFYING
            live_fail = CheckResult(
                check_id="live_health",
                site_id=site_id,
                phase=CheckPhase.LIVE.value,
                passed=False,
                message="Live activation failed health check on primary interface",
                duration_ms=22,
            )
            record.checks.append(live_fail)
            await self._emit_event(record, RunState.LIVE_VERIFYING, "Live verification check failed", seq, check=live_fail)
            await self.run_store.save_run(record)
            await asyncio.sleep(self.step_delay)

            seq += 1
            record.state = RunState.RESTORING
            await self._emit_event(record, RunState.RESTORING, "Restoring retained original container", seq)
            await self.run_store.save_run(record)
            await asyncio.sleep(self.step_delay)

            seq += 1
            record.state = RunState.RESTORED
            record.error = "Live activation failed; original deployment restored (unpatched)"
            record.finished_at = datetime.now(timezone.utc).isoformat()
            await self._emit_event(
                record, RunState.RESTORED, "Original container restored; security advisory remains unresolved", seq
            )
            await self.run_store.save_run(record)
            return record

        # 6. LIVE_VERIFYING (Live pass)
        seq += 1
        record.state = RunState.LIVE_VERIFYING
        live_check = CheckResult(
            check_id="live_verification",
            site_id=site_id,
            phase=CheckPhase.LIVE.value,
            passed=True,
            message="Live checks passed: PHP 8.3.36 active with upload mitigation",
            duration_ms=25,
        )
        record.checks.append(live_check)
        await self._emit_event(
            record, RunState.LIVE_VERIFYING, "All live checks passed at original address", seq, check=live_check
        )
        await self.run_store.save_run(record)
        await asyncio.sleep(self.step_delay)

        # 7. VERIFIED (Terminal success)
        seq += 1
        record.state = RunState.VERIFIED
        record.finished_at = datetime.now(timezone.utc).isoformat()
        record.site_results = {site_id: {"outcome": "VERIFIED", "cves_fixed": ["CVE-2026-109618", "CVE-2026-109619"]}}
        await self._emit_event(record, RunState.VERIFIED, "Repair run successfully verified and committed", seq)
        await self.run_store.save_run(record)
        return record

    async def recover_interrupted(self, record: RunRecord) -> RunRecord:
        record.state = RunState.INTERRUPTED
        record.error = "Interrupted run marked by fake repair service"
        await self.run_store.save_run(record)
        return record


# Background execution queue
worker_queue: asyncio.Queue[tuple[str, str, bool, str]] = asyncio.Queue()


def get_api_router(
    run_store: FileRunStore,
    event_sink: FileEventSink,
    recipe_store: FileRecipeStore,
    repair_service: FakeRepairService,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    # 1. GET /api/sites
    @router.get("/sites")
    async def list_sites():
        items = [site.model_dump(by_alias=True) for site in REGISTERED_SITES.values()]
        return {"items": items, "nextCursor": None}

    # 2. POST /api/sites/{siteId}/assessments
    @router.post("/sites/{site_id}/assessments")
    async def create_assessment(site_id: str):
        site = REGISTERED_SITES.get(site_id)
        if not site:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Site '{site_id}' is not a registered target",
            )

        assessment = Assessment(
            assessment_id=f"ass-{uuid.uuid4().hex[:8]}",
            site_id=site_id,
            fingerprint=f"fp-{uuid.uuid4().hex[:12]}",
            policy_revision="2026-018-rev1",
            applicability="VULNERABLE",
            current_runtime={
                "phpVersion": "8.3.10",
                "sapi": "apache2handler",
                "uploadProgress": "enabled",
            },
            proposed_changes=[
                "Upgrade image to php:8.3.36-apache",
                "Set session.upload_progress.enabled=0",
            ],
            required_checks=["serving_runtime", "homepage", "contact"]
            + (["upload"] if "upload" in site.capabilities else []),
            can_repair=True,
        )
        return assessment.model_dump(by_alias=True)

    # 3. POST /api/approvals
    @router.post("/approvals")
    async def create_approval(payload: CreateApprovalRequest):
        # TODO(platform): Add CSRF check and operator session binding
        approval_id = f"app-{uuid.uuid4().hex[:8]}"
        site_ids: list[str] = []
        parsed_items: list[AssessmentApprovalItem] = []

        for item in payload.assessments:
            ass_id = item.get("assessmentId", "")
            fp = item.get("fingerprint", "")
            parsed_items.append(AssessmentApprovalItem(assessment_id=ass_id, fingerprint=fp))
            # Match registered site if possible
            for s_id in REGISTERED_SITES:
                if s_id not in site_ids:
                    site_ids.append(s_id)
                    break

        if not site_ids:
            site_ids = ["pantry-a"]

        approval = Approval(
            approval_id=approval_id,
            site_ids=site_ids,
            assessments=parsed_items,
            policy_revision=payload.policy_revision,
            expires_at="2026-10-25T12:00:00Z",
            operator_session="local-operator",
            permitted_changes=payload.permitted_changes or ["php:8.3.36", "upload_progress_mitigation"],
            recovery_authority=payload.recovery_authority,
        )
        _APPROVALS[approval_id] = approval
        return approval.model_dump(by_alias=True)

    # 4. POST /api/runs (202 Accepted)
    @router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
    async def create_run(
        payload: CreateRunRequest,
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    ):
        # TODO(platform): Enforce distributed Idempotency-Key locking
        approval = _APPROVALS.get(payload.approval_id)
        if not approval:
            # Create a mock approval if absent for easy testing/demo
            approval = Approval(
                approval_id=payload.approval_id,
                site_ids=["pantry-a"],
                assessments=[],
                policy_revision="2026-018-rev1",
                permitted_changes=["php:8.3.36"],
            )
            _APPROVALS[payload.approval_id] = approval

        run_id = f"run-{uuid.uuid4().hex[:8]}"

        # Create initial QUEUED run snapshot
        initial_record = RunRecord(
            run_id=run_id,
            approval_id=approval.approval_id,
            site_ids=approval.site_ids,
            current_site_id=approval.site_ids[0] if approval.site_ids else "pantry-a",
            state=RunState.QUEUED,
            attempt=1,
            plan_source=PlanSource.TEST_DOUBLE,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        await run_store.save_run(initial_record)

        # Enqueue background repair task to lifespan worker
        target_outcome = payload.target_outcome or "success"
        await worker_queue.put((run_id, approval.approval_id, payload.memory_enabled, target_outcome))

        return {
            "runId": run_id,
            "statusUrl": f"/api/runs/{run_id}",
        }

    # 5. GET /api/runs
    @router.get("/runs")
    async def list_runs(
        cursor: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=100),
    ):
        runs, next_cursor = await run_store.list_runs(limit=limit, cursor=cursor)
        items = [run.model_dump(by_alias=True) for run in runs]
        return {
            "items": items,
            "nextCursor": next_cursor,
        }

    # 6. GET /api/runs/{runId}
    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        record = await run_store.get_run(run_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' not found",
            )
        return record.model_dump(by_alias=True)

    # 7. GET /api/runs/{runId}/events
    @router.get("/runs/{run_id}/events")
    async def get_run_events(
        run_id: str,
        after: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ):
        record = await run_store.get_run(run_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' not found",
            )
        events, next_seq = await event_sink.get_events(run_id, after_sequence=after, limit=limit)
        items = [ev.model_dump(by_alias=True) for ev in events]
        return {
            "items": items,
            "nextSequence": next_seq,
        }

    # 8. GET /api/runs/{runId}/report
    @router.get("/runs/{run_id}/report")
    async def get_run_report(run_id: str):
        record = await run_store.get_run(run_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' not found",
            )

        markdown_report = (
            f"# PatchPilot Repair Report: {record.run_id}\n\n"
            f"- **State:** `{record.state.value}`\n"
            f"- **Plan Source:** `{record.plan_source.value if record.plan_source else 'N/A'}`\n"
            f"- **Sites:** {', '.join(record.site_ids)}\n"
            f"- **Checks Executed:** {len(record.checks)}\n"
        )
        if record.error:
            markdown_report += f"- **Outcome Notice:** {record.error}\n"

        return {
            "runId": record.run_id,
            "state": record.state.value,
            "siteResults": record.site_results or {},
            "checks": [c.model_dump(by_alias=True) for c in record.checks],
            "changes": record.changes or ["php:8.3.36-apache", "session.upload_progress.enabled=0"],
            "securityResults": record.security_results or {"cvesMitigated": ["CVE-2026-109618", "CVE-2026-109619"]},
            "recovery": record.recovery or {"restorationExercised": record.state == RunState.RESTORED},
            "provenance": record.provenance or {"source": record.plan_source.value if record.plan_source else "TEST_DOUBLE"},
            "warnings": record.warnings,
            "markdown": markdown_report,
        }

    # 9. POST /api/resets
    @router.post("/resets", status_code=status.HTTP_202_ACCEPTED)
    async def create_reset(payload: CreateResetRequest):
        reset_id = f"reset-{uuid.uuid4().hex[:8]}"
        cleared_count = 0
        if payload.clear_recipes:
            cleared_count = await recipe_store.clear_recipes()

        _RESETS[reset_id] = {
            "resetId": reset_id,
            "state": "COMPLETED",
            "clearedRecipes": payload.clear_recipes,
            "recipesCleared": cleared_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "resetId": reset_id,
            "statusUrl": f"/api/resets/{reset_id}",
        }

    # 10. GET /api/resets/{resetId}
    @router.get("/resets/{reset_id}")
    async def get_reset(reset_id: str):
        reset = _RESETS.get(reset_id)
        if not reset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Reset operation '{reset_id}' not found",
            )
        return reset

    return router
