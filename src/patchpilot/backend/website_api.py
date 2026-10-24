"""Public website assessment endpoints; reads and jobs belong to one session."""

import json
import os
import stat
from hashlib import sha256
from pathlib import Path
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
        "kind": "assessment only",
        "connectionSupport": "ASSESSMENT_ONLY",
        "description": "An intentionally vulnerable public testing demo. Collect fresh public responses; repository repair access is not provided.",
        "sourceUrl": "https://www.invicti.com/blog/docs-and-faqs/fix-vulnerabilities-faster-bidirectional-invicti-jira-integration",
    },
    {
        "id": "php-official",
        "title": "PHP official website",
        "url": "https://www.php.net/",
        "kind": "assessment only",
        "connectionSupport": "ASSESSMENT_ONLY",
        "description": "The PHP project's public website. Assess its current responses; a sample listing does not establish that a site is safe.",
        "sourceUrl": "https://www.php.net/",
    },
    {
        "id": "phpipam-demo",
        "title": "phpIPAM public demo",
        "url": "https://demo.phpipam.net/",
        "kind": "assessment only",
        "connectionSupport": "ASSESSMENT_ONLY",
        "description": "The public phpIPAM demonstration. Assess fresh response evidence; no repository connection or repair permission is included.",
        "sourceUrl": "https://phpipam.net/demo/",
    },
]
MAX_DEMO_METADATA_BYTES = 16 * 1024
MAX_CONNECTED_EXAMPLES = 5


class CreateWebsiteAssessment(ContractModel):
    url: str = Field(min_length=1, max_length=2048)


def validate_url(url: str) -> str:
    from patchpilot.webscan.network import validate_public_url

    canonical = validate_public_url(url)
    parsed = urlsplit(canonical)
    if parsed.query or parsed.fragment:
        raise ValueError("Use a public page URL without query parameters or fragments")
    return canonical


def connected_examples(directory: Path) -> list[dict[str, str]]:
    """Read only small regular public metadata; configuration is not repair proof."""
    path = directory / "public.json"
    try:
        if directory.is_symlink():
            return []
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DEMO_METADATA_BYTES:
                return []
            raw = handle.read(MAX_DEMO_METADATA_BYTES + 1)
        if len(raw) > MAX_DEMO_METADATA_BYTES:
            return []
        metadata = json.loads(raw)
        entries = (
            metadata.get("items")
            if isinstance(metadata, dict) and "items" in metadata
            else [metadata]
        )
        if (
            not isinstance(entries, list)
            or not 1 <= len(entries) <= MAX_CONNECTED_EXAMPLES
        ):
            return []
    except (OSError, ValueError, TypeError):
        return []

    from patchpilot.repairs.github import repository_name

    result, seen = [], set()
    for demo in entries:
        try:
            if not isinstance(demo, dict) or set(demo) != {"url", "repositoryUrl"}:
                continue
            if (
                not isinstance(demo["url"], str)
                or not isinstance(demo["repositoryUrl"], str)
                or len(demo["repositoryUrl"]) > 500
            ):
                continue
            if urlsplit(demo["url"]).fragment:
                continue
            url = validate_url(demo["url"])
            if urlsplit(url).path != "/":
                continue
            repository = repository_name(demo["repositoryUrl"])
        except (ValueError, KeyError, TypeError):
            continue
        identity = url, repository.lower()
        if identity in seen:
            continue
        seen.add(identity)
        suffix = sha256(f"{url}\0{repository.lower()}".encode()).hexdigest()[:12]
        result.append(
            {
                "id": "connected-php-demo"
                if not result
                else f"connected-php-demo-{suffix}",
                "title": "Connected PHP community demo"
                if not result
                else f"Connected PHP community demo {len(result) + 1}",
                "url": url,
                "kind": "connected repair demo",
                "connectionSupport": "CONNECTED",
                "description": "A configured PHP repository demo. Connection still requires the supported source profile and a matching deployment marker; each assessment collects fresh evidence.",
                "sourceUrl": f"https://github.com/{repository}",
                "repositoryUrl": f"https://github.com/{repository}",
            }
        )
    return result


def get_website_router() -> APIRouter:
    router = APIRouter(prefix="/api/website-assessments")

    @router.get("/examples")
    async def examples(request: Request, session_id: str = Depends(operator_session)):
        directory = request.app.state.run_store.runs_dir.parent / "connected-demo"
        return {"items": [*connected_examples(directory), *EXAMPLES]}

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
