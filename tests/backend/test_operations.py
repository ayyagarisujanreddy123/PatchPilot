"""Operation admission, idempotency, recovery, and orderly shutdown."""

import asyncio
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from fastapi.testclient import TestClient
import pytest

from patchpilot.backend.app import create_app
from patchpilot.backend.fake import FakeRepairService
from patchpilot.backend.control import OperationControl
from patchpilot.shared.contracts import RunState
from tests.backend.test_api import approve, wait_run


@contextmanager
def service_client(service):
    with TestClient(create_app(service.run_store, service.event_sink, service.recipe_store, service)) as client:
        csrf = client.get("/api/session").json()["csrfToken"]
        client.headers.update({"X-CSRF-Token": csrf, "Origin": "http://testserver"})
        yield client


class GatedService(FakeRepairService):
    def __init__(self, *args):
        super().__init__(*args, step_delay=0.001)
        self.entered = threading.Event()
        self.allow = asyncio.Event()

    async def run(self, *args, **kwargs):
        self.entered.set()
        await self.allow.wait()
        return await super().run(*args, **kwargs)


def test_run_replay_and_conflict_while_every_other_operation_is_busy(run_store, event_sink, recipe_store):
    service = GatedService(run_store, event_sink, recipe_store)
    with service_client(service) as client:
        approval = approve(client)
        body = {"approvalId": approval["approvalId"]}
        first = client.post("/api/runs", json=body, headers={"Idempotency-Key": "same-intent"})
        assert first.status_code == 202
        assert service.entered.wait(2)
        try:
            replay = client.post("/api/runs", json=body, headers={"Idempotency-Key": "same-intent"})
            assert replay.status_code == 202
            assert replay.json() == first.json()
            conflict = client.post("/api/runs", json={**body, "memoryEnabled": False}, headers={"Idempotency-Key": "same-intent"})
            assert conflict.status_code == 409
            assert client.post("/api/runs", json=body, headers={"Idempotency-Key": "different-intent"}).status_code == 409
            assert client.post("/api/resets", json={}).status_code == 409
            assert client.post("/api/prepare", json={}).status_code == 409
            assert client.post("/api/assessments", json={"siteId": "pantry-a"}).status_code == 409
            assert client.get("/api/health").json()["activeOperation"] == {"kind": "run", "id": first.json()["runId"]}
        finally:
            client.portal.call(service.allow.set)
        assert wait_run(client, first.json()["runId"])["state"] == "VERIFIED"
        assert len(client.get("/api/runs").json()["items"]) == 1
        replay = client.post("/api/runs", json=body, headers={"Idempotency-Key": "same-intent"})
        assert replay.json() == first.json()


def test_prepare_reserves_the_controller_during_real_work(run_store, event_sink, recipe_store):
    class PrepareGate(GatedService):
        async def prepare(self):
            self.entered.set()
            await self.allow.wait()
            return await FakeRepairService.prepare(self)

    service = PrepareGate(run_store, event_sink, recipe_store)
    with service_client(service) as client, ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(client.post, "/api/prepare", json={})
        assert service.entered.wait(2)
        try:
            assert client.get("/api/health").json()["activeOperation"]["kind"] == "prepare"
            assert client.post("/api/resets", json={}).status_code == 409
        finally:
            client.portal.call(service.allow.set)
        assert result.result(timeout=2).json()["state"] == "COMPLETED"
        assert client.get("/api/health").json()["busy"] is False


def test_worker_failure_before_checkpoint_preserves_queued_recovery_marker(run_store, event_sink, recipe_store):
    class CrashingService(FakeRepairService):
        async def run(self, *args, **kwargs):
            raise RuntimeError("SECRET_MUST_NOT_REACH_OWNER")

        async def recover_interrupted(self, record):
            assert record.state == RunState.QUEUED
            return await super().recover_interrupted(record)

    service = CrashingService(run_store, event_sink, recipe_store)
    with service_client(service) as client:
        approval = approve(client)
        result = client.post("/api/runs", json={"approvalId": approval["approvalId"]}, headers={"Idempotency-Key": "worker-crash"})
        record = wait_run(client, result.json()["runId"])
        assert record["state"] == "INTERRUPTED"
        assert record["evidenceComplete"] is True
        assert "SECRET" not in str(record)
        for _ in range(100):
            if not client.get("/api/health").json()["busy"]:
                break
            time.sleep(0.005)
        assert client.get("/api/health").json()["busy"] is False


def test_unverified_recovery_retains_reservation(run_store, event_sink, recipe_store):
    class FailedRecovery(FakeRepairService):
        async def run(self, *args, **kwargs):
            raise RuntimeError("synthetic operation failure")

        async def recover_interrupted(self, record):
            raise RuntimeError("synthetic recovery failure")

    service = FailedRecovery(run_store, event_sink, recipe_store)
    with service_client(service) as client:
        approval = approve(client)
        result = client.post("/api/runs", json={"approvalId": approval["approvalId"]}, headers={"Idempotency-Key": "unverified"})
        for _ in range(100):
            record = client.get(result.json()["statusUrl"]).json()
            if record["state"] == "RECOVERY_FAILED":
                break
            time.sleep(0.005)
        assert record["state"] == "RECOVERY_FAILED"
        assert record["evidenceComplete"] is False
        assert client.get("/api/health").json()["busy"] is True
        assert client.post("/api/prepare", json={}).status_code == 409


def test_shutdown_drains_run_before_closing_dependencies(run_store, event_sink, recipe_store):
    class ShutdownService(FakeRepairService):
        finished = False
        closed = False

        async def run(self, *args, **kwargs):
            await asyncio.sleep(0.03)
            result = await super().run(*args, **kwargs)
            self.finished = True
            return result

        def close(self):
            assert self.finished
            self.closed = True

    service = ShutdownService(run_store, event_sink, recipe_store, step_delay=0.001)
    with service_client(service) as client:
        approval = approve(client)
        assert client.post("/api/runs", json={"approvalId": approval["approvalId"]}, headers={"Idempotency-Key": "shutdown"}).status_code == 202
    assert service.finished and service.closed


def test_second_controller_cannot_use_same_storage(run_store, event_sink, recipe_store):
    service = FakeRepairService(run_store, event_sink, recipe_store)
    with service_client(service):
        second = FakeRepairService(run_store, event_sink, recipe_store)
        with pytest.raises(RuntimeError, match="Another PatchPilot controller"):
            with service_client(second):
                pass


@pytest.mark.asyncio
async def test_idempotency_records_survive_coordinator_restart(tmp_path):
    first = OperationControl(tmp_path / "runs")
    await first.open()
    key = first.replay_key("operator-session", "client-key")
    first.idempotency[key] = {"requestDigest": "digest", "response": {"runId": "run-persisted"}}
    await first.persist()
    first.close()
    second = OperationControl(tmp_path / "runs")
    await second.open()
    try:
        assert second.idempotency[key]["response"]["runId"] == "run-persisted"
        assert "operator-session" not in (second.directory / "operations.json").read_text()
    finally:
        second.close()


@pytest.mark.asyncio
async def test_cancelled_request_waits_for_offloaded_operation_before_releasing(tmp_path):
    from patchpilot.backend.control import complete_before_cancel

    control = OperationControl(tmp_path / "runs")
    await control.open()
    started, finish = asyncio.Event(), asyncio.Event()

    async def actual_operation():
        started.set()
        await finish.wait()

    async def request():
        async with control.operation("prepare", "prepare-cancellation"):
            await complete_before_cancel(actual_operation())

    task = asyncio.create_task(request())
    try:
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert control.active == {"kind": "prepare", "id": "prepare-cancellation"}
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert control.active is None
    finally:
        finish.set()
        control.close()
