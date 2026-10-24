"""Durable, session-owned repository verification and explicit publication jobs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field

from patchpilot.backend.control import OperationControl, complete_before_cancel
from patchpilot.backend.storage import _atomic_write_text, _safe_identifier
from patchpilot.repairs.models import (
    Capability,
    GitHubStatus,
    RepairEvent,
    RepositoryConnection,
    RepositoryRepairReport,
)
from patchpilot.shared.contracts import ContractModel
from patchpilot.webscan.models import ScanReport

logger = logging.getLogger(__name__)
TERMINAL = {"READY_TO_PUBLISH", "NO_CHANGE", "REJECTED", "PUBLISHED", "FAILED"}
OPERATION_ERRORS = (
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    LookupError,
    AttributeError,
    AssertionError,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def require_fresh(timestamp: str | None, description: str) -> None:
    try:
        parsed = datetime.fromisoformat(timestamp or "")
        if parsed.tzinfo is None:
            raise ValueError("A timezone is required")
        age = (datetime.now(UTC) - parsed).total_seconds()
        if age < -60 or age > 3600:
            raise ValueError("Evidence is outside its freshness window")
    except (TypeError, ValueError):
        raise HTTPException(
            409, f"{description} must be completed within the last hour"
        ) from None


class RepositoryService(Protocol):
    def status(self) -> GitHubStatus: ...

    def connect(
        self,
        assessment: ScanReport,
        repository_url: str,
        capabilities: list[Capability],
    ) -> RepositoryConnection: ...

    def repair(
        self,
        connection: RepositoryConnection,
        *,
        repair_id: str,
        emit: Callable[[RepositoryRepairReport], None],
    ) -> RepositoryRepairReport: ...

    def publish(
        self,
        connection: RepositoryConnection,
        report: RepositoryRepairReport,
        *,
        emit: Callable[[RepositoryRepairReport], None],
    ) -> RepositoryRepairReport: ...


class StoredConnection(ContractModel):
    schema_version: Literal[1] = 1
    owner_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    connection: RepositoryConnection


class StoredRepair(ContractModel):
    schema_version: Literal[1] = 1
    owner_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    report: RepositoryRepairReport
    ready_at: str | None = None
    publication_key_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    publication_started_at: str | None = None


class RepositoryJobManager:
    """One finite sync service call at a time, including across lab/website jobs."""

    def __init__(
        self,
        directory: Path,
        control: OperationControl,
        service_factory: Callable[[], RepositoryService],
    ):
        self.directory, self.control, self.service_factory = (
            directory,
            control,
            service_factory,
        )
        self.connections: dict[str, StoredConnection] = {}
        self.records: dict[str, StoredRepair] = {}
        self.storage_failed: set[str] = set()
        self.closing = False
        self._task: asyncio.Task | None = None
        self._status_task: asyncio.Task | None = None
        self._active_id: str | None = None
        self._service: RepositoryService | None = None
        self._service_lock = threading.Lock()
        self.session_rate_limit, self.global_rate_limit, self.rate_window = 5, 10, 60.0
        self._starts: deque[tuple[float, str]] = deque()

    @staticmethod
    def owner(session_id: str) -> str:
        return hashlib.sha256(session_id.encode()).hexdigest()

    def _get_service(self) -> RepositoryService:
        with self._service_lock:
            if self._service is None:
                self._service = self.service_factory()
            return self._service

    def _connection_path(self, connection_id: str) -> Path:
        return (
            self.directory / "connections" / f"{_safe_identifier(connection_id)}.json"
        )

    def _report_path(self, repair_id: str) -> Path:
        return self.directory / "reports" / f"{_safe_identifier(repair_id)}.json"

    async def _save_connection(self, entry: StoredConnection) -> None:
        entry = entry.model_copy(deep=True)
        await asyncio.to_thread(
            _atomic_write_text,
            self._connection_path(entry.connection.connection_id),
            entry.model_dump_json(by_alias=True, indent=2),
        )
        self.connections[entry.connection.connection_id] = entry

    async def _save(self, entry: StoredRepair) -> None:
        entry = entry.model_copy(deep=True)
        await asyncio.to_thread(
            _atomic_write_text,
            self._report_path(entry.report.repair_id),
            entry.model_dump_json(by_alias=True, indent=2),
        )
        self.records[entry.report.repair_id] = entry

    @staticmethod
    def _event(report: RepositoryRepairReport, message: str) -> None:
        report.events.append(
            RepairEvent(
                sequence=max((event.sequence for event in report.events), default=0)
                + 1,
                timestamp=now(),
                state=report.state,
                message=message,
            )
        )

    def _failure(
        self, report: RepositoryRepairReport, message: str
    ) -> RepositoryRepairReport:
        failed = report.model_copy(deep=True)
        failed.state, failed.error, failed.stage_message = "FAILED", message, message
        failed.finished_at = now()
        self._event(failed, message)
        return failed

    async def open(self) -> None:
        for path in sorted((self.directory / "connections").glob("*.json")):
            try:
                entry = StoredConnection.model_validate_json(
                    await asyncio.to_thread(path.read_text, encoding="utf-8")
                )
                if self._connection_path(entry.connection.connection_id) != path:
                    raise ValueError("Connection identity mismatch")
            except (OSError, ValueError):
                raise RuntimeError(
                    "A saved repository connection is unreadable"
                ) from None
            self.connections[entry.connection.connection_id] = entry
        for path in sorted((self.directory / "reports").glob("*.json")):
            try:
                entry = StoredRepair.model_validate_json(
                    await asyncio.to_thread(path.read_text, encoding="utf-8")
                )
                connection = self.connections[entry.report.connection_id]
                if (
                    self._report_path(entry.report.repair_id) != path
                    or entry.owner_hash != connection.owner_hash
                ):
                    raise ValueError("Repair identity mismatch")
                self._validate_identity(entry.report, connection.connection)
            except (OSError, ValueError, KeyError):
                raise RuntimeError("A saved repository repair is unreadable") from None
            if entry.report.state not in TERMINAL:
                message = (
                    "Controller stopped during pull-request publication. Retry publication for this repair to reconcile its existing branch and pull request."
                    if entry.publication_started_at
                    else "Controller stopped before repository verification completed. Start a fresh repair; recorded evidence is retained."
                )
                entry.report = self._failure(entry.report, message)
                await self._save(entry)
            else:
                self.records[entry.report.repair_id] = entry

    def _check_admission(self, owner_hash: str) -> None:
        if self.closing:
            raise HTTPException(503, "The repository repair worker is shutting down")
        if self.control.active:
            raise HTTPException(409, "Another operation is active or needs recovery")
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
                "Repository operation rate limit reached. Try again shortly.",
                headers={"Retry-After": str(retry)},
            )

    async def status(self) -> GitHubStatus:
        if self.closing:
            raise HTTPException(503, "The repository repair worker is shutting down")
        if self._status_task is None or self._status_task.done():
            self._status_task = asyncio.create_task(
                asyncio.to_thread(
                    lambda: GitHubStatus.model_validate(
                        self._get_service().status().model_dump()
                    )
                )
            )
        return await complete_before_cancel(self._status_task)

    async def connect(
        self,
        assessment: ScanReport,
        repository_url: str,
        capabilities: list[Capability],
        session_id: str,
    ) -> RepositoryConnection:
        if assessment.state != "COMPLETED":
            raise HTTPException(
                409, "Complete the website assessment before connecting a repository"
            )
        require_fresh(assessment.finished_at, "The website assessment")
        owner_hash = self.owner(session_id)
        async with self.control.lock:
            self._check_admission(owner_hash)
            operation_id = f"connection-{uuid4().hex}"
            await self.control.reserve_unlocked("repository-connection", operation_id)
            self._starts.append((time.monotonic(), owner_hash))
            self._task = asyncio.create_task(
                self._connect(
                    assessment.model_copy(deep=True),
                    repository_url,
                    capabilities[:],
                    owner_hash,
                    operation_id,
                )
            )
        return await complete_before_cancel(self._task)

    async def _connect(
        self,
        assessment: ScanReport,
        repository_url: str,
        capabilities: list[Capability],
        owner_hash: str,
        operation_id: str,
    ) -> RepositoryConnection:
        try:
            connection = await asyncio.to_thread(
                lambda: self._get_service().connect(
                    assessment, repository_url, capabilities
                )
            )
            connection = RepositoryConnection.model_validate(connection.model_dump())
            if (
                connection.assessment_id != assessment.assessment_id
                or connection.url != assessment.url
                or connection.capabilities != capabilities
            ):
                raise ValueError(
                    "The connection does not match its website assessment and selected checks"
                )
            if connection.connection_id in self.connections:
                raise ValueError(
                    "A repository connection cannot replace an existing connection"
                )
            require_fresh(connection.created_at, "The repository connection")
            await self._save_connection(
                StoredConnection(owner_hash=owner_hash, connection=connection)
            )
            return connection.model_copy(deep=True)
        finally:
            await self.control.release(operation_id)

    def get_connection(
        self, connection_id: str, session_id: str
    ) -> RepositoryConnection:
        entry = self.connections.get(connection_id)
        if entry is None or entry.owner_hash != self.owner(session_id):
            raise HTTPException(
                404, "Repository connection does not exist for this session"
            )
        return entry.connection.model_copy(deep=True)

    def list_connections(
        self, session_id: str, assessment_id: str | None = None
    ) -> list[RepositoryConnection]:
        reports = [
            entry.connection
            for entry in self.connections.values()
            if entry.owner_hash == self.owner(session_id)
            and (
                assessment_id is None or entry.connection.assessment_id == assessment_id
            )
        ]
        return sorted(
            reports, key=lambda connection: connection.created_at, reverse=True
        )[:50]

    async def submit(
        self, connection_id: str, session_id: str
    ) -> RepositoryRepairReport:
        connection = self.get_connection(connection_id, session_id)
        require_fresh(connection.created_at, "The repository connection")
        owner_hash = self.owner(session_id)
        async with self.control.lock:
            self._check_admission(owner_hash)
            report = RepositoryRepairReport(
                repair_id=f"repair-{uuid4().hex}",
                connection_id=connection.connection_id,
                assessment_id=connection.assessment_id,
                repository=connection.repository,
                url=connection.url,
                base_commit=connection.base_commit,
                capabilities=connection.capabilities,
                created_at=now(),
            )
            await self.control.reserve_unlocked("repository-repair", report.repair_id)
            try:
                await self._save(StoredRepair(owner_hash=owner_hash, report=report))
            except Exception:
                await self._rollback_reservation()
                raise
            self._starts.append((time.monotonic(), owner_hash))
            self._active_id = report.repair_id
            self._task = asyncio.create_task(
                self._execute(connection, report, publish=False)
            )
        return report.model_copy(deep=True)

    async def _rollback_reservation(self) -> None:
        self.control.active = None
        await self.control.persist()

    @staticmethod
    def _validate_identity(
        report: RepositoryRepairReport, connection: RepositoryConnection
    ) -> None:
        expected = (
            connection.connection_id,
            connection.assessment_id,
            connection.repository,
            connection.url,
            connection.base_commit,
            connection.capabilities,
        )
        observed = (
            report.connection_id,
            report.assessment_id,
            report.repository,
            report.url,
            report.base_commit,
            report.capabilities,
        )
        if observed != expected:
            raise ValueError(
                "Repair progress must remain bound to its connected commit and selected checks"
            )

    async def _progress(
        self,
        queued: RepositoryRepairReport,
        connection: RepositoryConnection,
        report: RepositoryRepairReport,
        *,
        publish: bool,
    ) -> None:
        if (
            not isinstance(report, RepositoryRepairReport)
            or report.repair_id != queued.repair_id
            or self._active_id != queued.repair_id
        ):
            raise ValueError("Repair progress must belong to its active job")
        report = RepositoryRepairReport.model_validate(report.model_dump())
        self._validate_identity(report, connection)
        if (publish and report.state not in {"PUBLISHING", "PUBLISHED", "FAILED"}) or (
            not publish and report.state in {"PUBLISHING", "PUBLISHED"}
        ):
            raise ValueError("Publication requires its separate explicit operation")
        if publish and any(
            getattr(report, field) != getattr(queued, field)
            for field in ("patch", "proposal", "checks", "image_digest")
        ):
            raise ValueError(
                "Publication cannot replace its recorded verification proof"
            )
        if report.state == "READY_TO_PUBLISH" and (
            not report.patch
            or not report.proposal
            or not report.finished_at
            or {check.phase for check in report.checks} != {"BASELINE", "CANDIDATE"}
            or not all(
                check.passed for check in report.checks if check.phase == "CANDIDATE"
            )
        ):
            raise ValueError(
                "A ready repair requires complete baseline and passing candidate proof"
            )
        if report.state == "PUBLISHED" and not report.pull_request:
            raise ValueError("Publication must return its existing pull request")
        report.created_at = queued.created_at
        entry = self.records[queued.repair_id].model_copy(deep=True)
        entry.report = report
        if report.state == "READY_TO_PUBLISH" and entry.ready_at is None:
            entry.ready_at = report.finished_at or now()
        await self._save(entry)

    async def publish(
        self, repair_id: str, session_id: str, key: str
    ) -> RepositoryRepairReport:
        report = self.get(repair_id, session_id)
        connection = self.get_connection(report.connection_id, session_id)
        key_hash = self.control.replay_key(session_id, f"repository-publication:{key}")
        async with self.control.lock:
            entry = self.records[repair_id].model_copy(deep=True)
            if any(
                other.publication_key_hash == key_hash
                and other.report.repair_id != repair_id
                for other in self.records.values()
            ):
                raise HTTPException(
                    409, "Idempotency-Key is already bound to a different repair"
                )
            if entry.publication_key_hash and entry.publication_key_hash != key_hash:
                raise HTTPException(
                    409,
                    "Retry this repair with its original publication Idempotency-Key",
                )
            if entry.report.state == "PUBLISHED":
                return entry.report.model_copy(deep=True)
            if entry.report.state == "PUBLISHING" and self._active_id == repair_id:
                return entry.report.model_copy(deep=True)
            retry = bool(entry.publication_started_at and entry.publication_key_hash)
            if not retry:
                if entry.report.state != "READY_TO_PUBLISH" or not entry.report.patch:
                    raise HTTPException(
                        409,
                        "Only an isolated verified repair can create a pull request",
                    )
                require_fresh(
                    entry.ready_at or entry.report.finished_at,
                    "The repair verification",
                )
                require_fresh(connection.created_at, "The repository connection")
            elif entry.report.state != "FAILED":
                raise HTTPException(409, "This publication is not ready to be retried")
            self._check_admission(entry.owner_hash)
            await self.control.reserve_unlocked("repository-publication", repair_id)
            entry.publication_key_hash = key_hash
            entry.publication_started_at = entry.publication_started_at or now()
            entry.report.state, entry.report.finished_at, entry.report.error = (
                "PUBLISHING",
                None,
                None,
            )
            entry.report.stage_message = (
                "Reconciling the existing pull request"
                if retry
                else "Publishing the verified repair as a draft pull request"
            )
            self._event(entry.report, entry.report.stage_message)
            try:
                await self._save(entry)
            except Exception:
                await self._rollback_reservation()
                raise
            self._starts.append((time.monotonic(), entry.owner_hash))
            self._active_id = repair_id
            self._task = asyncio.create_task(
                self._execute(connection, entry.report, publish=True)
            )
            return entry.report.model_copy(deep=True)

    async def _execute(
        self,
        connection: RepositoryConnection,
        queued: RepositoryRepairReport,
        *,
        publish: bool,
    ) -> None:
        loop = asyncio.get_running_loop()
        persisted = False
        allowed = {"PUBLISHED", "FAILED"} if publish else TERMINAL - {"PUBLISHED"}

        def emit(report: RepositoryRepairReport) -> None:
            asyncio.run_coroutine_threadsafe(
                self._progress(
                    queued, connection, report.model_copy(deep=True), publish=publish
                ),
                loop,
            ).result()

        def run_service() -> RepositoryRepairReport:
            try:
                service = self._get_service()
                if publish:
                    return service.publish(
                        connection.model_copy(deep=True),
                        queued.model_copy(deep=True),
                        emit=emit,
                    )
                return service.repair(
                    connection.model_copy(deep=True),
                    repair_id=queued.repair_id,
                    emit=emit,
                )
            except Exception as exc:
                # Normalize unexpected transport/provider exceptions at the worker
                # boundary without preserving sensitive exception text or traces.
                logger.exception(
                    "Repository service execution failed (%s)",
                    type(exc).__name__,
                    exc_info=False,
                )
                raise RuntimeError("Repository service execution failed") from None

        try:
            report = await asyncio.to_thread(run_service)
            if (
                not isinstance(report, RepositoryRepairReport)
                or report.state not in allowed
            ):
                raise ValueError(
                    "The repository service did not return a terminal report"
                )
            await self._progress(queued, connection, report, publish=publish)
            persisted = True
        except OPERATION_ERRORS as exc:
            logger.error("Repository operation failed (%s)", type(exc).__name__)
            entry = self.records[queued.repair_id].model_copy(deep=True)
            message = (
                "Pull-request publication could not complete. Retry publication for this repair to reconcile its existing branch and pull request."
                if publish
                else "Repository verification could not complete. Recorded evidence is retained; no verified repair is claimed."
            )
            if entry.report.state not in allowed:
                entry.report = self._failure(entry.report, message)
            try:
                await self._save(entry)
                persisted = True
            except (OSError, TypeError, ValueError) as storage_error:
                logger.error(
                    "Repository repair persistence failed (%s)",
                    type(storage_error).__name__,
                )
                self.storage_failed.add(queued.repair_id)
        finally:
            self._active_id = None
            if persisted:
                try:
                    await self.control.release(queued.repair_id)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    logger.error(
                        "Repository reservation could not be released (%s)",
                        type(exc).__name__,
                    )
                    self.storage_failed.add(queued.repair_id)

    def get(self, repair_id: str, session_id: str) -> RepositoryRepairReport:
        entry = self.records.get(repair_id)
        if entry is None or entry.owner_hash != self.owner(session_id):
            raise HTTPException(
                404, "Repository repair does not exist for this session"
            )
        if repair_id in self.storage_failed:
            raise HTTPException(
                503, "Repair progress could not be persisted; check controller storage"
            )
        return entry.report.model_copy(deep=True)

    def list(
        self,
        session_id: str,
        *,
        connection_id: str | None = None,
        assessment_id: str | None = None,
    ) -> list[RepositoryRepairReport]:
        reports = [
            entry.report
            for entry in self.records.values()
            if entry.owner_hash == self.owner(session_id)
            and (connection_id is None or entry.report.connection_id == connection_id)
            and (assessment_id is None or entry.report.assessment_id == assessment_id)
        ]
        return sorted(reports, key=lambda report: report.created_at, reverse=True)[:50]

    async def shutdown(self) -> None:
        self.closing = True
        for task in (self._task, self._status_task):
            if task is not None:
                if task.done():
                    if not task.cancelled():
                        task.exception()
                    continue
                try:
                    await complete_before_cancel(task)
                except (*OPERATION_ERRORS, HTTPException) as exc:
                    logger.error(
                        "Repository request ended during shutdown (%s)",
                        type(exc).__name__,
                    )
