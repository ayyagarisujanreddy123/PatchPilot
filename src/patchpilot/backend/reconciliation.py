"""Startup reconciliation stub for interrupted runs and orphaned container resources.

TODO(platform): Implement multi-node restart reconciliation:
1. Scan var/runs/ for runs left in non-terminal states (ASSESSING, PLANNING, STAGING, VERIFYING, ACTIVATING, RESTORING).
2. Query Docker daemon for owned container labels matching the active run.
3. Call Sujan's Core.recover_interrupted(record, dependencies) to resolve state or mark INTERRUPTED/RECOVERY_FAILED.
4. Release stale process busy-locks.
"""

from __future__ import annotations

import logging
from typing import Optional

from patchpilot.shared.contracts import RunRecord, RunState
from patchpilot.shared.ports import RepairService, RunStore

logger = logging.getLogger("patchpilot.backend.reconciliation")


async def reconcile_interrupted_runs(
    run_store: RunStore, repair_service: Optional[RepairService] = None
) -> int:
    """Scan and reconcile incomplete runs on startup."""
    # TODO(platform): Full implementation wired to Sujan's core recovery service
    runs, _ = await run_store.list_runs(limit=100)
    reconciled_count = 0
    non_terminal = {
        RunState.QUEUED,
        RunState.ASSESSING,
        RunState.PLANNING,
        RunState.STAGING,
        RunState.VERIFYING,
        RunState.REVISING,
        RunState.ACTIVATING,
        RunState.LIVE_VERIFYING,
        RunState.RESTORING,
    }

    for run in runs:
        if run.state in non_terminal:
            logger.warning("Found incomplete run %s in state %s during startup", run.run_id, run.state)
            if repair_service:
                await repair_service.recover_interrupted(run)
            else:
                # Fallback: mark as INTERRUPTED so it is not permanently stuck
                run.state = RunState.INTERRUPTED
                run.error = "Process terminated while run was active"
                await run_store.save_run(run)
            reconciled_count += 1

    return reconciled_count
