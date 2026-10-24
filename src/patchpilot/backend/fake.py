"""Explicit simulation service for tests; never selected by application defaults."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import secrets
import uuid

from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.contracts import (
    Approval, Assessment, AssessmentApprovalItem, CheckResult, PlanSource,
    RunEvent, RunRecord, RunState, SiteManifest,
)

REGISTERED_SITES: dict[str, SiteManifest] = {
    name: SiteManifest(
        site_id=name, display_name=name.replace("-", " ").title(),
        base_url=f"http://127.0.0.1:{8081 + index}",
        capabilities=["homepage", "contact"] + (["upload"] if name.startswith("clinic") else []),
        assessment_state="UNASSESSED", template_revision=f"{name.split('-')[0]}-v1",
        expected_content="Community Health Clinic" if name.startswith("clinic") else "Community Food Pantry",
    )
    for index, name in enumerate(("pantry-a", "pantry-b", "clinic-a", "clinic-b"))
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeRepairService:
    """Synthetic evidence and outcomes, visibly marked SIMULATION/TEST_DOUBLE."""

    def __init__(self, run_store: FileRunStore, event_sink: FileEventSink, recipe_store: FileRecipeStore, step_delay: float = 0.05):
        self.run_store, self.event_sink, self.recipe_store = run_store, event_sink, recipe_store
        self.step_delay = step_delay
        self.assessments: dict[str, Assessment] = {}
        self.approvals: dict[str, Approval] = {}
        self.sites = {key: value.model_copy(deep=True) for key, value in REGISTERED_SITES.items()}
        self.prepared = False

    async def list_sites(self) -> list[SiteManifest]:
        return list(self.sites.values())

    async def health(self) -> dict:
        return {"mode": "SIMULATION", "ready": True, "prepared": self.prepared, "dockerAvailable": False, "plannerConfigured": False, "message": "Explicit simulation: no deployments or model requests"}

    async def assess(self, site_id: str) -> Assessment:
        if site_id not in self.sites:
            raise LookupError("Site is not a registered local target")
        item = Assessment(
            assessment_id=f"ass-{uuid.uuid4().hex}", site_id=site_id,
            fingerprint=secrets.token_hex(32), policy_revision="simulation-v1",
            applicability="SIMULATED", current_runtime={"source": "TEST_DOUBLE"},
            proposed_changes=["Simulate the approved PHP repair"],
            required_checks=["homepage", "contact"] + (["upload"] if "upload" in self.sites[site_id].capabilities else []),
            can_repair=True,
        )
        self.assessments[item.assessment_id] = item
        return item

    async def approve(self, items: list[AssessmentApprovalItem], policy_revision: str, operator_session: str) -> Approval:
        if not items or policy_revision != "simulation-v1":
            raise ValueError("A current, nonempty assessment selection is required")
        site_ids: list[str] = []
        for item in items:
            assessment = self.assessments.get(item.assessment_id)
            if not assessment:
                raise LookupError("Assessment does not exist")
            if item.fingerprint != assessment.fingerprint or assessment.policy_revision != policy_revision:
                raise ValueError("Assessment fingerprint or policy has changed")
            if assessment.site_id in site_ids:
                raise ValueError("Each site may be approved only once")
            site_ids.append(assessment.site_id)
        approval = Approval(
            approval_id=f"app-{uuid.uuid4().hex}", site_ids=site_ids, assessments=items,
            policy_revision=policy_revision,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            operator_session=operator_session,
            permitted_changes=["php83_patched", "preserve_basic", "preserve_uploads"],
        )
        self.approvals[approval.approval_id] = approval
        return approval

    async def get_approval(self, approval_id: str, operator_session: str) -> Approval:
        item = self.approvals.get(approval_id)
        if not item or item.operator_session != operator_session:
            raise LookupError("Approval does not exist for this operator session")
        if not item.expires_at or datetime.fromisoformat(item.expires_at) <= datetime.now(timezone.utc):
            raise ValueError("Approval has expired")
        return item

    async def run(self, approval: Approval, memory_enabled: bool = True, *, run_id: str | None = None, target_outcome: str | None = None) -> RunRecord:
        run_id = run_id or f"run-{uuid.uuid4().hex}"
        record = await self.run_store.get_run(run_id) or RunRecord(run_id=run_id, approval_id=approval.approval_id, site_ids=approval.site_ids)
        record.plan_source = PlanSource.TEST_DOUBLE
        record.started_at = utc_now()
        record.warnings = ["SIMULATION: all observations and outcomes are synthetic"]
        record.site_results = {}
        sequence = 0

        async def emit(state: RunState, message: str, check: CheckResult | None = None) -> None:
            nonlocal sequence
            sequence += 1
            record.state = state
            if check:
                record.checks.append(check)
            await self.event_sink.append_event(run_id, RunEvent(sequence=sequence, timestamp=utc_now(), site_id=record.current_site_id, state=state, message=f"SIMULATION: {message}", check=check))
            await self.run_store.save_run(record)
            await asyncio.sleep(self.step_delay)

        await emit(RunState.QUEUED, "run queued")
        for site_id in approval.site_ids:
            record.current_site_id = site_id
            for state in (RunState.ASSESSING, RunState.PLANNING, RunState.STAGING):
                await emit(state, state.value.lower())
            if target_outcome == "reject_staging":
                await emit(RunState.VERIFYING, "synthetic staging failure", CheckResult(check_id="upload_size", site_id=site_id, phase="STAGING", passed=False, message="Synthetic upload limit failure"))
                record.attempt = 2
                await emit(RunState.REVISING, "synthetic second attempt")
                terminal = RunState.REJECTED
                record.error = "SIMULATION: candidate attempts exhausted; original untouched"
            else:
                await emit(RunState.VERIFYING, "synthetic candidate check", CheckResult(check_id="homepage", site_id=site_id, phase="STAGING", passed=True, message="Synthetic homepage check"))
                await emit(RunState.ACTIVATING, "synthetic activation")
                await emit(RunState.LIVE_VERIFYING, "synthetic live check", CheckResult(check_id="homepage", site_id=site_id, phase="LIVE", passed=target_outcome != "restore_activation", message="Synthetic live homepage check"))
                if target_outcome == "restore_activation":
                    await emit(RunState.RESTORING, "synthetic restoration")
                    terminal = RunState.RESTORED
                    record.error = "SIMULATION: original restored; deployment remains unpatched"
                else:
                    terminal = RunState.VERIFIED
            record.site_results[site_id] = {"outcome": terminal.value, "simulation": True}
            self.sites[site_id].last_run_id = run_id
            self.sites[site_id].assessment_state = terminal.value
            await emit(terminal, "synthetic terminal outcome")
        record.finished_at = utc_now()
        record.evidence_complete = True
        record.provenance = {"source": "TEST_DOUBLE", "simulation": True}
        await self.run_store.save_run(record)
        return record

    async def prepare(self) -> dict:
        self.prepared = True
        for site in self.sites.values():
            site.last_run_id = None
            site.assessment_state = "UNASSESSED"
        return {"state": "COMPLETED", "mode": "SIMULATION", "sites": []}

    async def reset(self, clear_recipes: bool = False) -> dict:
        result = await self.prepare()
        return {**result, "clearedRecipes": await self.recipe_store.clear_recipes() if clear_recipes else 0}

    async def recover_interrupted(self, record: RunRecord) -> RunRecord:
        record.state = RunState.INTERRUPTED
        record.error = "SIMULATION: interrupted run; no real deployment was changed"
        record.evidence_complete = True
        record.finished_at = utc_now()
        await self.run_store.save_run(record)
        return record

    def close(self) -> None:
        pass
