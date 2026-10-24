"""Recover every unfinished or incompletely evidenced run before serving writes."""

from __future__ import annotations

from patchpilot.shared.contracts import RunState
from patchpilot.shared.ports import RepairService, RunStore

TERMINAL_STATES = {
    RunState.VERIFIED, RunState.REJECTED, RunState.BLOCKED, RunState.RESTORED,
    RunState.RECOVERY_FAILED, RunState.INTERRUPTED,
}


async def reconcile_interrupted_runs(run_store: RunStore, repair_service: RepairService) -> int:
    cursor = None
    pending = []
    while True:
        records, cursor = await run_store.list_runs(limit=100, cursor=cursor)
        pending.extend(record for record in records if record.state not in TERMINAL_STATES or not record.evidence_complete)
        if cursor is None:
            break
    for record in pending:
        try:
            await repair_service.recover_interrupted(record)
        except Exception:
            record.state = RunState.RECOVERY_FAILED
            record.error = "Startup recovery could not verify the deployment; operator recovery is required"
            record.evidence_complete = False
            await run_store.save_run(record)
    return len(pending)
