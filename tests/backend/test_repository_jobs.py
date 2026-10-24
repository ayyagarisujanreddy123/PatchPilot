"""Failure and cancellation boundaries retain durable repository job ownership."""

import asyncio
import threading
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from patchpilot.backend.control import OperationControl, complete_before_cancel
from patchpilot.backend.repository_jobs import RepositoryJobManager, StoredConnection
from patchpilot.repairs.models import (
    RepositoryConnection,
    RepositoryRepairReport,
    SiteManifest,
)
from patchpilot.webscan.models import ScanReport


def now():
    return datetime.now(UTC).isoformat()


def connection():
    return RepositoryConnection(
        connection_id="connection-tested",
        assessment_id="website-tested",
        url="https://www.php.net/",
        repository="owner/site",
        repository_url="https://github.com/owner/site",
        default_branch="main",
        base_commit="a" * 40,
        site_id="site-tested",
        created_at=now(),
        manifest=SiteManifest(
            site_id="site-tested",
            document_root="public",
            php_ini="php.ini",
            capabilities=["homepage"],
        ),
        capabilities=["homepage"],
    )


def report_for(bound, repair_id, **update):
    return RepositoryRepairReport(
        repair_id=repair_id,
        connection_id=bound.connection_id,
        assessment_id=bound.assessment_id,
        repository=bound.repository,
        url=bound.url,
        base_commit=bound.base_commit,
        capabilities=bound.capabilities,
        created_at=now(),
        **update,
    )


class InvalidService:
    def __init__(self, mode):
        self.mode = mode

    def repair(self, bound, *, repair_id, emit):
        report = report_for(bound, repair_id, state="FETCHING")
        emit(report)
        if self.mode == "identity":
            report.base_commit = "b" * 40
            emit(report)
        elif self.mode == "unauthorized-publication":
            report.state = "PUBLISHED"
            emit(report)
        else:
            report.state, report.finished_at = "READY_TO_PUBLISH", now()
        return report


@pytest.mark.parametrize(
    "mode", ["identity", "unauthorized-publication", "incomplete-proof"]
)
async def test_invalid_service_progress_cannot_change_bound_identity_or_claim_success(
    tmp_path, mode
):
    control = OperationControl(tmp_path / "runs")
    await control.open()
    manager = RepositoryJobManager(
        tmp_path / "repository-repairs", control, lambda: InvalidService(mode)
    )
    bound = connection()
    await manager._save_connection(
        StoredConnection(owner_hash=manager.owner("session"), connection=bound)
    )
    try:
        queued = await manager.submit(bound.connection_id, "session")
        await manager._task
        failed = manager.get(queued.repair_id, "session")
        assert failed.state == "FAILED"
        assert failed.base_commit == bound.base_commit
        assert failed.patch is None
        assert failed.pull_request is None
        assert control.active is None
    finally:
        await manager.shutdown()
        control.close()


async def test_storage_failure_retains_global_reservation_and_fails_report_reads(
    tmp_path, monkeypatch
):
    control = OperationControl(tmp_path / "runs")
    await control.open()
    manager = RepositoryJobManager(
        tmp_path / "repository-repairs",
        control,
        lambda: InvalidService("incomplete-proof"),
    )
    bound = connection()
    await manager._save_connection(
        StoredConnection(owner_hash=manager.owner("session"), connection=bound)
    )
    save = manager._save

    async def failing_save(entry):
        if entry.report.state != "QUEUED":
            raise OSError("PRIVATE_STORAGE_PATH")
        await save(entry)

    monkeypatch.setattr(manager, "_save", failing_save)
    try:
        queued = await manager.submit(bound.connection_id, "session")
        await manager._task
        with pytest.raises(HTTPException) as failure:
            manager.get(queued.repair_id, "session")
        assert failure.value.status_code == 503
        assert control.active == {"kind": "repository-repair", "id": queued.repair_id}
        with pytest.raises(HTTPException) as busy:
            await manager.submit(bound.connection_id, "session")
        assert busy.value.status_code == 409
    finally:
        await manager.shutdown()
        control.close()


async def test_cancelled_connection_request_waits_for_actual_thread_and_durable_connection(
    tmp_path,
):
    class SlowConnectionService:
        entered, allow = threading.Event(), threading.Event()

        def connect(self, assessment, repository_url, capabilities):
            self.entered.set()
            if not self.allow.wait(3):
                raise RuntimeError("Test gate timed out")
            return connection()

    service = SlowConnectionService()
    control = OperationControl(tmp_path / "runs")
    await control.open()
    manager = RepositoryJobManager(
        tmp_path / "repository-repairs", control, lambda: service
    )
    scan = ScanReport(
        assessment_id="website-tested",
        url="https://www.php.net/",
        state="COMPLETED",
        created_at=now(),
        finished_at=now(),
    )
    operation = asyncio.create_task(
        complete_before_cancel(
            manager.connect(
                scan, "https://github.com/owner/site", ["homepage"], "session"
            )
        )
    )
    try:
        assert await asyncio.to_thread(service.entered.wait, 2)
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done()
        assert control.active["kind"] == "repository-connection"
        service.allow.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert (
            manager.get_connection("connection-tested", "session").base_commit
            == "a" * 40
        )
        assert control.active is None
    finally:
        service.allow.set()
        await manager.shutdown()
        control.close()


async def test_shutdown_rejects_admission_already_waiting_for_the_global_lock(tmp_path):
    control = OperationControl(tmp_path / "runs")
    await control.open()
    manager = RepositoryJobManager(
        tmp_path / "repository-repairs", control, lambda: InvalidService("identity")
    )
    bound = connection()
    await manager._save_connection(
        StoredConnection(owner_hash=manager.owner("session"), connection=bound)
    )
    try:
        async with control.lock:
            pending = asyncio.create_task(
                manager.submit(bound.connection_id, "session")
            )
            await asyncio.sleep(0)
            manager.closing = True
        with pytest.raises(HTTPException) as failure:
            await pending
        assert failure.value.status_code == 503
        assert control.active is None
        assert not manager.records
    finally:
        await manager.shutdown()
        control.close()


async def test_unknown_provider_exception_becomes_a_safe_terminal_report(
    tmp_path, caplog
):
    class ProviderTransportError(Exception):
        pass

    class FailingProvider:
        def repair(self, bound, *, repair_id, emit):
            emit(report_for(bound, repair_id, state="PLANNING"))
            raise ProviderTransportError("PRIVATE_REQUEST_AUTHORIZATION")

    control = OperationControl(tmp_path / "runs")
    await control.open()
    manager = RepositoryJobManager(
        tmp_path / "repository-repairs", control, FailingProvider
    )
    bound = connection()
    await manager._save_connection(
        StoredConnection(owner_hash=manager.owner("session"), connection=bound)
    )
    try:
        queued = await manager.submit(bound.connection_id, "session")
        await manager._task
        report = manager.get(queued.repair_id, "session")
        assert report.state == "FAILED"
        assert "PRIVATE_REQUEST" not in report.model_dump_json()
        assert "PRIVATE_REQUEST" not in caplog.text
        assert all(not record.exc_info for record in caplog.records)
        assert report.patch is None
        assert control.active is None
    finally:
        await manager.shutdown()
        control.close()
