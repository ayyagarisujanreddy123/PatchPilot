"""Restart admission uses every unfinished record, including later pages."""

import pytest

from patchpilot.backend.reconciliation import reconcile_interrupted_runs
from patchpilot.shared.contracts import RunRecord, RunState


@pytest.mark.asyncio
async def test_startup_recovery_reaches_runs_beyond_first_page(run_store, fast_repair_service):
    for number in range(105):
        await run_store.save_run(RunRecord(run_id=f"run-paged-{number}", state=RunState.QUEUED))
    assert await reconcile_interrupted_runs(run_store, fast_repair_service) == 105
    cursor = None
    recovered = []
    while True:
        records, cursor = await run_store.list_runs(limit=100, cursor=cursor)
        recovered.extend(records)
        if cursor is None:
            break
    assert len(recovered) == 105
    assert all(record.state == RunState.INTERRUPTED and record.evidence_complete for record in recovered)


@pytest.mark.asyncio
async def test_recovery_error_persists_explicit_failure(run_store):
    record = RunRecord(run_id="run-uncertain", state=RunState.ACTIVATING, checkpoint={"original": {"deployment_id": "retained"}})
    await run_store.save_run(record)

    class UnavailableRecovery:
        async def recover_interrupted(self, record):
            raise RuntimeError("SECRET_ADAPTER_DETAIL")

    assert await reconcile_interrupted_runs(run_store, UnavailableRecovery()) == 1
    recovered = await run_store.get_run(record.run_id)
    assert recovered.state == RunState.RECOVERY_FAILED
    assert recovered.evidence_complete is False
    assert recovered.checkpoint == record.checkpoint
    assert "SECRET" not in recovered.error


@pytest.mark.asyncio
async def test_complete_verified_history_is_not_recovered(run_store):
    await run_store.save_run(RunRecord(run_id="run-finished", state=RunState.VERIFIED, evidence_complete=True))

    class NeverRecover:
        async def recover_interrupted(self, record):
            raise AssertionError("Completed history must remain unchanged")

    assert await reconcile_interrupted_runs(run_store, NeverRecover()) == 0
    assert (await run_store.get_run("run-finished")).state == RunState.VERIFIED
