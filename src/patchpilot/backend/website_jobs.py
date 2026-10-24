"""Durable, session-owned website jobs with one bounded active worker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field

from patchpilot.backend.control import OperationControl, complete_before_cancel
from patchpilot.backend.storage import _atomic_write_text, _safe_identifier
from patchpilot.shared.contracts import ContractModel
from patchpilot.webscan.models import ScanEvent, ScanReport

logger = logging.getLogger(__name__)
TERMINAL = {"COMPLETED", "FAILED"}


class WebsiteAgent(Protocol):
    def run(
        self, url: str, *, assessment_id: str, emit: Callable[[ScanReport], None]
    ) -> ScanReport: ...


class StoredAssessment(ContractModel):
    schema_version: int = 1
    owner_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    report: ScanReport


def now() -> str:
    return datetime.now(UTC).isoformat()


class WebsiteJobManager:
    """The sync agent owns finite transport/provider deadlines; shutdown drains it."""

    def __init__(
        self,
        directory: Path,
        control: OperationControl,
        agent_factory: Callable[[], WebsiteAgent],
    ):
        self.directory, self.control, self.agent_factory = (
            directory,
            control,
            agent_factory,
        )
        self.records: dict[str, StoredAssessment] = {}
        self.storage_failed: set[str] = set()
        self._task: asyncio.Task | None = None
        self._active_id: str | None = None
        self.closing = False
        self.session_rate_limit, self.global_rate_limit, self.rate_window = 5, 10, 60.0
        self._starts: deque[tuple[float, str]] = deque()

    @staticmethod
    def owner(session_id: str) -> str:
        return hashlib.sha256(session_id.encode()).hexdigest()

    def _path(self, assessment_id: str) -> Path:
        return self.directory / f"{_safe_identifier(assessment_id)}.json"

    async def _save(self, entry: StoredAssessment) -> None:
        # Copy before yielding: a synchronous producer may reuse its report object.
        entry = entry.model_copy(deep=True)
        await asyncio.to_thread(
            _atomic_write_text,
            self._path(entry.report.assessment_id),
            entry.model_dump_json(by_alias=True, indent=2),
        )
        self.records[entry.report.assessment_id] = entry

    def _failure(self, report: ScanReport, message: str) -> ScanReport:
        failed = report.model_copy(deep=True)
        failed.state, failed.error, failed.stage_message = "FAILED", message, message
        failed.finished_at = now()
        failed.events.append(
            ScanEvent(
                sequence=max((event.sequence for event in failed.events), default=0)
                + 1,
                timestamp=now(),
                stage="FAILED",
                message=message,
            )
        )
        return failed

    async def open(self) -> None:
        if not self.directory.exists():
            return
        for path in sorted(self.directory.glob("*.json")):
            try:
                entry = StoredAssessment.model_validate_json(
                    await asyncio.to_thread(path.read_text, encoding="utf-8")
                )
                if self._path(entry.report.assessment_id) != path:
                    raise ValueError("Assessment identity mismatch")
            except (OSError, ValueError):
                raise RuntimeError("A saved website assessment is unreadable") from None
            if entry.report.state not in TERMINAL:
                entry.report = self._failure(
                    entry.report,
                    "Controller stopped before the assessment completed. Start a fresh assessment.",
                )
                await self._save(entry)
            else:
                self.records[entry.report.assessment_id] = entry

    def _check_rate(self, owner_hash: str) -> None:
        instant = time.monotonic()
        while self._starts and self._starts[0][0] <= instant - self.rate_window:
            self._starts.popleft()
        own = [started for started, owner in self._starts if owner == owner_hash]
        candidates = (
            own
            if len(own) >= self.session_rate_limit
            else [started for started, _ in self._starts]
            if len(self._starts) >= self.global_rate_limit
            else []
        )
        if candidates:
            retry = max(1, math.ceil(candidates[0] + self.rate_window - instant))
            raise HTTPException(
                429,
                "Website assessment rate limit reached. Try again shortly.",
                headers={"Retry-After": str(retry)},
            )

    async def submit(self, url: str, session_id: str) -> ScanReport:
        if self.closing:
            raise HTTPException(503, "The website assessment worker is shutting down")
        owner_hash = self.owner(session_id)
        async with self.control.lock:
            if self.closing:
                raise HTTPException(
                    503, "The website assessment worker is shutting down"
                )
            if self.control.active:
                raise HTTPException(
                    409, "Another operation is active or needs recovery"
                )
            self._check_rate(owner_hash)
            assessment_id = f"website-{uuid4().hex}"
            report = ScanReport(assessment_id=assessment_id, url=url, created_at=now())
            await self.control.reserve_unlocked("website-assessment", assessment_id)
            try:
                await self._save(StoredAssessment(owner_hash=owner_hash, report=report))
            except Exception:
                self.control.active = None
                await self.control.persist()
                raise
            self._starts.append((time.monotonic(), owner_hash))
            self._active_id = assessment_id
            self._task = asyncio.create_task(self._execute(report, owner_hash))
        return report

    async def _progress(
        self, queued: ScanReport, owner_hash: str, report: ScanReport
    ) -> None:
        if (
            not isinstance(report, ScanReport)
            or report.assessment_id != queued.assessment_id
            or self._active_id != queued.assessment_id
        ):
            raise ValueError("Agent progress must belong to its active assessment")
        report = ScanReport.model_validate(report.model_dump())
        report = report.model_copy(
            deep=True, update={"url": queued.url, "created_at": queued.created_at}
        )
        await self._save(StoredAssessment(owner_hash=owner_hash, report=report))

    async def _execute(self, queued: ScanReport, owner_hash: str) -> None:
        loop = asyncio.get_running_loop()
        persisted = False

        def emit(report: ScanReport) -> None:
            # Return only after this complete typed checkpoint is on disk.
            asyncio.run_coroutine_threadsafe(
                self._progress(queued, owner_hash, report), loop
            ).result()

        def run_agent() -> ScanReport:
            return self.agent_factory().run(
                queued.url, assessment_id=queued.assessment_id, emit=emit
            )

        try:
            report = await asyncio.to_thread(run_agent)
            if not isinstance(report, ScanReport) or report.state not in TERMINAL:
                raise ValueError("The website agent did not return a terminal report")
            await self._progress(queued, owner_hash, report)
            persisted = True
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.error("Website assessment failed (%s)", type(exc).__name__)
            latest = self.records[queued.assessment_id].report
            failed = (
                latest
                if latest.state == "FAILED" and latest.error
                else self._failure(
                    latest,
                    "Website assessment could not complete. Recorded observations are retained; no successful result is claimed.",
                )
            )
            try:
                await self._save(StoredAssessment(owner_hash=owner_hash, report=failed))
                persisted = True
            except (OSError, TypeError, ValueError) as storage_error:
                logger.error(
                    "Website assessment persistence failed (%s)",
                    type(storage_error).__name__,
                )
                self.storage_failed.add(queued.assessment_id)
        finally:
            self._active_id = None
            if persisted:
                try:
                    await self.control.release(queued.assessment_id)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    logger.error(
                        "Website reservation could not be released (%s)",
                        type(exc).__name__,
                    )
                    self.storage_failed.add(queued.assessment_id)

    def get(self, assessment_id: str, session_id: str) -> ScanReport:
        entry = self.records.get(assessment_id)
        if entry is None or entry.owner_hash != self.owner(session_id):
            raise HTTPException(
                404, "Website assessment does not exist for this session"
            )
        if assessment_id in self.storage_failed:
            raise HTTPException(
                503,
                "Assessment progress could not be persisted; check controller storage",
            )
        return entry.report

    def list(self, session_id: str) -> list[ScanReport]:
        owner_hash = self.owner(session_id)
        reports = [
            entry.report
            for entry in self.records.values()
            if entry.owner_hash == owner_hash
        ]
        return sorted(reports, key=lambda report: report.created_at, reverse=True)[:50]

    async def shutdown(self) -> None:
        self.closing = True
        if self._task is not None:
            await complete_before_cancel(self._task)
