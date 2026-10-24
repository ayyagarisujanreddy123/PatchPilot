"""Connected repository repairs; publication always requires a separate mutation."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import Field, field_validator

from patchpilot.backend.control import (
    complete_before_cancel,
    operator_session,
    require_mutation,
)
from patchpilot.repairs.models import Capability
from patchpilot.shared.contracts import ContractModel


class CreateConnection(ContractModel):
    assessment_id: str = Field(min_length=1, max_length=100)
    repository_url: str = Field(min_length=1, max_length=500)
    capabilities: list[Capability] = Field(min_length=1, max_length=3)

    @field_validator("capabilities")
    @classmethod
    def selected_checks(cls, value: list[Capability]) -> list[Capability]:
        if "homepage" not in value or len(value) != len(set(value)):
            raise ValueError("Select homepage and unique supported business checks")
        return value


class CreateRepair(ContractModel):
    connection_id: str = Field(min_length=1, max_length=100)


def accepted(report):
    return {
        "repairId": report.repair_id,
        "statusUrl": f"/api/repository-repairs/{report.repair_id}",
    }


def get_repository_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/repository-connections/status")
    async def status(request: Request, session_id: str = Depends(operator_session)):
        result = await request.app.state.repository_jobs.status()
        return result.model_dump(by_alias=True)

    @router.post("/repository-connections", status_code=201)
    async def connect(
        payload: CreateConnection,
        request: Request,
        session_id: str = Depends(require_mutation),
    ):
        assessment = request.app.state.website_jobs.get(
            payload.assessment_id, session_id
        )
        result = await complete_before_cancel(
            request.app.state.repository_jobs.connect(
                assessment,
                payload.repository_url,
                payload.capabilities,
                session_id,
            )
        )
        return result.model_dump(by_alias=True)

    @router.get("/repository-connections")
    async def connections(
        request: Request,
        assessment_id: str | None = Query(None, alias="assessmentId", max_length=100),
        session_id: str = Depends(operator_session),
    ):
        return {
            "items": [
                connection.model_dump(by_alias=True)
                for connection in request.app.state.repository_jobs.list_connections(
                    session_id, assessment_id
                )
            ],
            "nextCursor": None,
        }

    @router.post("/repository-repairs", status_code=202)
    async def repair(
        payload: CreateRepair,
        request: Request,
        session_id: str = Depends(require_mutation),
    ):
        result = await complete_before_cancel(
            request.app.state.repository_jobs.submit(payload.connection_id, session_id)
        )
        return accepted(result)

    @router.get("/repository-repairs")
    async def repairs(
        request: Request,
        connection_id: str | None = Query(None, alias="connectionId", max_length=100),
        assessment_id: str | None = Query(None, alias="assessmentId", max_length=100),
        session_id: str = Depends(operator_session),
    ):
        return {
            "items": [
                report.model_dump(by_alias=True)
                for report in request.app.state.repository_jobs.list(
                    session_id, connection_id=connection_id, assessment_id=assessment_id
                )
            ],
            "nextCursor": None,
        }

    @router.get("/repository-repairs/{repair_id}")
    async def report(
        repair_id: str, request: Request, session_id: str = Depends(operator_session)
    ):
        return request.app.state.repository_jobs.get(repair_id, session_id).model_dump(
            by_alias=True
        )

    @router.post("/repository-repairs/{repair_id}/pull-request", status_code=202)
    async def publish(
        repair_id: str,
        request: Request,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=8, max_length=200
        ),
        session_id: str = Depends(require_mutation),
    ):
        if not idempotency_key.strip() or any(
            ord(character) < 33 or ord(character) > 126 for character in idempotency_key
        ):
            raise HTTPException(400, "Use a printable Idempotency-Key without spaces")
        result = await complete_before_cancel(
            request.app.state.repository_jobs.publish(
                repair_id, session_id, idempotency_key
            )
        )
        return accepted(result)

    return router
