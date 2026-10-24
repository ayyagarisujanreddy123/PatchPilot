"""Public website assessment endpoints; reads and jobs belong to one session."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from patchpilot.backend.control import operator_session, require_mutation
from patchpilot.shared.contracts import ContractModel

EXAMPLES = [
    {
        "id": "invicti-php-demo",
        "title": "Invicti PHP test site",
        "url": "http://php.testsparker.com/",
        "kind": "intentionally vulnerable demo",
        "description": "Provider-owned public testing demo. This assessment uses normal GET requests and records fresh observations.",
        "sourceUrl": "https://www.invicti.com/blog/docs-and-faqs/fix-vulnerabilities-faster-bidirectional-invicti-jira-integration",
    }
]


class CreateWebsiteAssessment(ContractModel):
    url: str = Field(min_length=1, max_length=2048)


def validate_url(url: str) -> str:
    from patchpilot.webscan.network import validate_public_url

    canonical = validate_public_url(url)
    parsed = urlsplit(canonical)
    if parsed.query or parsed.fragment:
        raise ValueError("Use a public page URL without query parameters or fragments")
    return canonical


def get_website_router() -> APIRouter:
    router = APIRouter(prefix="/api/website-assessments")

    @router.get("/examples")
    async def examples(session_id: str = Depends(operator_session)):
        return {"items": EXAMPLES}

    @router.post("", status_code=202)
    async def create(
        payload: CreateWebsiteAssessment,
        request: Request,
        session_id: str = Depends(require_mutation),
    ):
        report = await request.app.state.website_jobs.submit(
            validate_url(payload.url), session_id
        )
        return {
            "assessmentId": report.assessment_id,
            "statusUrl": f"/api/website-assessments/{report.assessment_id}",
        }

    @router.get("")
    async def collection(request: Request, session_id: str = Depends(operator_session)):
        return {
            "items": [
                report.model_dump(by_alias=True)
                for report in request.app.state.website_jobs.list(session_id)
            ],
            "nextCursor": None,
        }

    @router.get("/{assessment_id}")
    async def report(
        assessment_id: str,
        request: Request,
        session_id: str = Depends(operator_session),
    ):
        return request.app.state.website_jobs.get(assessment_id, session_id).model_dump(
            by_alias=True
        )

    return router
