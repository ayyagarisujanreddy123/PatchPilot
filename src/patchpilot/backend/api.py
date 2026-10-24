"""Session-bound API for the real repair service and explicit test simulations."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import secrets
import time
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import Field

from patchpilot.backend.control import OperationControl, SESSION_COOKIE, SESSION_MAX_AGE, complete_before_cancel, require_mutation
from patchpilot.backend.fake import FakeRepairService as FakeRepairService
from patchpilot.backend.fake import REGISTERED_SITES as REGISTERED_SITES
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.contracts import (
    AssessmentApprovalItem, ContractModel, RunRecord, RunState,
)
from patchpilot.shared.ports import RepairService


class CreateAssessmentRequest(ContractModel):
    site_id: str


class CreateApprovalRequest(ContractModel):
    assessments: list[AssessmentApprovalItem] = Field(min_length=1, max_length=4)
    policy_revision: str = Field(min_length=1, max_length=128)


class CreateRunRequest(ContractModel):
    approval_id: str = Field(min_length=1, max_length=128)
    memory_enabled: bool = True
    target_outcome: Literal["success", "reject_staging", "restore_activation"] | None = None


class CreateResetRequest(ContractModel):
    clear_recipes: bool = False


class PrepareRequest(ContractModel):
    pass


def _service(request: Request) -> RepairService:
    return request.app.state.repair_service


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_api_router(
    run_store: FileRunStore,
    event_sink: FileEventSink,
    recipe_store: FileRecipeStore,
    repair_service: RepairService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/session")
    async def session(request: Request, response: Response):
        control: OperationControl = request.app.state.control
        session_id = request.cookies.get(SESSION_COOKIE, "")
        if session_id not in control.sessions or control.session_expiry.get(session_id, 0) <= time.time():
            control.sessions.pop(session_id, None)
            control.session_expiry.pop(session_id, None)
            session_id = secrets.token_urlsafe(32)
            control.sessions[session_id] = secrets.token_urlsafe(32)
            control.session_expiry[session_id] = time.time() + SESSION_MAX_AGE
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/", max_age=SESSION_MAX_AGE)
        response.headers["Cache-Control"] = "no-store"
        return {"csrfToken": control.sessions[session_id]}

    @router.get("/health")
    async def health(request: Request):
        control: OperationControl = request.app.state.control
        result = await _service(request).health()
        return {**result, "busy": control.active is not None, "activeOperation": control.active}

    @router.get("/sites")
    async def sites(request: Request):
        items = await _service(request).list_sites()
        return {"items": [item.model_dump(by_alias=True) for item in items], "nextCursor": None}

    async def assess_site(site_id: str, request: Request, session_id: str):
        control: OperationControl = request.app.state.control
        async with control.operation("assessment", f"assessment-{uuid.uuid4().hex}"):
            assessment = await complete_before_cancel(_service(request).assess(site_id))
            control.assessment_owners[assessment.assessment_id] = session_id
            return assessment.model_dump(by_alias=True)

    @router.post("/sites/{site_id}/assessments")
    async def site_assessment(site_id: str, request: Request, session_id: str = Depends(require_mutation)):
        return await assess_site(site_id, request, session_id)

    @router.post("/assessments")
    async def assessment(payload: CreateAssessmentRequest, request: Request, session_id: str = Depends(require_mutation)):
        return await assess_site(payload.site_id, request, session_id)

    @router.post("/approvals")
    async def approval(payload: CreateApprovalRequest, request: Request, session_id: str = Depends(require_mutation)):
        control: OperationControl = request.app.state.control
        for item in payload.assessments:
            if control.assessment_owners.get(item.assessment_id) != session_id:
                raise HTTPException(404, "Assessment does not exist for this operator session")
        item = await _service(request).approve(payload.assessments, payload.policy_revision, session_id)
        # The operator session is an opaque server-side authority, never API evidence.
        return item.model_dump(by_alias=True, exclude={"operator_session"})

    @router.post("/runs", status_code=202)
    async def create_run(
        payload: CreateRunRequest, request: Request,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
        session_id: str = Depends(require_mutation),
    ):
        if not idempotency_key or len(idempotency_key) > 128 or not idempotency_key.isprintable():
            raise HTTPException(400, "A printable Idempotency-Key of at most 128 characters is required")
        control: OperationControl = request.app.state.control
        service = _service(request)
        mode = (await service.health()).get("mode")
        if payload.target_outcome is not None and mode != "SIMULATION":
            raise HTTPException(400, "targetOutcome is available only in explicit simulation mode")
        digest = hashlib.sha256(json.dumps(payload.model_dump(), sort_keys=True).encode()).hexdigest()
        replay_key = control.replay_key(session_id, idempotency_key)
        async with control.lock:
            previous = control.idempotency.get(replay_key)
            if previous:
                if previous["requestDigest"] != digest:
                    raise HTTPException(409, "This Idempotency-Key was used for a different request")
                return previous["response"]
            approval = await service.get_approval(payload.approval_id, session_id)
            queue = getattr(request.app.state, "worker_queue", None)
            if queue is None:
                raise HTTPException(503, "Repair worker is not running")
            run_id = f"run-{uuid.uuid4().hex}"
            await control.reserve_unlocked("run", run_id)
            try:
                await run_store.save_run(RunRecord(
                    run_id=run_id, approval_id=approval.approval_id, site_ids=approval.site_ids,
                    current_site_id=approval.site_ids[0], state=RunState.QUEUED,
                    created_at=_now(), updated_at=_now(),
                ))
                result = {"runId": run_id, "statusUrl": f"/api/runs/{run_id}"}
                control.idempotency[replay_key] = {"requestDigest": digest, "response": result}
                await control.persist()
                queue.put_nowait({"kind": "run", "id": run_id, "approvalId": approval.approval_id, "session": session_id, "memoryEnabled": payload.memory_enabled, "targetOutcome": payload.target_outcome})
            except Exception:
                control.idempotency.pop(replay_key, None)
                control.active = None
                await control.persist()
                raise
        return result

    @router.get("/runs")
    async def list_runs(cursor: str | None = Query(None), limit: int = Query(50, ge=1, le=100)):
        runs, next_cursor = await run_store.list_runs(limit=limit, cursor=cursor)
        return {"items": [item.model_dump(by_alias=True) for item in runs], "nextCursor": next_cursor}

    async def require_run(run_id: str) -> RunRecord:
        record = await run_store.get_run(run_id)
        if not record:
            raise HTTPException(404, "Run does not exist")
        return record

    @router.get("/runs/{run_id}")
    async def run(run_id: str):
        return (await require_run(run_id)).model_dump(by_alias=True)

    @router.get("/runs/{run_id}/events")
    async def events(run_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        await require_run(run_id)
        items, next_sequence = await event_sink.get_events(run_id, after_sequence=after, limit=limit)
        return {"items": [item.model_dump(by_alias=True) for item in items], "nextSequence": next_sequence}

    @router.get("/runs/{run_id}/report")
    async def report(run_id: str):
        record = await require_run(run_id)
        text = f"# PatchPilot Repair Report: {record.run_id}\n\nState: {record.state.value}\n\nEvidence complete: {record.evidence_complete}\n"
        if record.error:
            text += f"\nOutcome: {record.error}\n"
        return {
            "runId": record.run_id, "state": record.state.value,
            "siteResults": record.site_results or {}, "checks": [check.model_dump(by_alias=True) for check in record.checks],
            "changes": record.changes or [], "securityResults": record.security_results or {},
            "recovery": record.recovery or {}, "provenance": record.provenance or {},
            "evidenceComplete": record.evidence_complete, "warnings": record.warnings, "markdown": text,
        }

    @router.post("/prepare")
    async def prepare(request: Request, payload: PrepareRequest = PrepareRequest(), session_id: str = Depends(require_mutation)):
        control: OperationControl = request.app.state.control
        async with control.operation("prepare", f"prepare-{uuid.uuid4().hex}"):
            result = await complete_before_cancel(_service(request).prepare())
            control.assessment_owners.clear()
            return result

    @router.post("/resets", status_code=202)
    async def create_reset(payload: CreateResetRequest, request: Request, session_id: str = Depends(require_mutation)):
        control: OperationControl = request.app.state.control
        if getattr(request.app.state, "worker_queue", None) is None:
            raise HTTPException(503, "Operation worker is not running")
        reset_id = f"reset-{uuid.uuid4().hex}"
        async with control.lock:
            await control.reserve_unlocked("reset", reset_id)
            try:
                control.resets[reset_id] = {"resetId": reset_id, "state": "QUEUED"}
                await control.persist()
                request.app.state.worker_queue.put_nowait({"kind": "reset", "id": reset_id, "clearRecipes": payload.clear_recipes})
            except Exception:
                control.active = None
                control.resets.pop(reset_id, None)
                await control.persist()
                raise
        return {"resetId": reset_id, "statusUrl": f"/api/resets/{reset_id}"}

    @router.get("/resets/{reset_id}")
    async def reset(reset_id: str, request: Request):
        result = request.app.state.control.resets.get(reset_id)
        if not result:
            raise HTTPException(404, "Reset does not exist")
        return result

    return router
