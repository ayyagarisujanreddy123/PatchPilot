"""Application integration without Docker or paid model calls."""

from dataclasses import replace

import pytest

from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.core.ports import PlanSource, ProposedPlan
from patchpilot.core.service import RealRepairService
from patchpilot.shared.contracts import AssessmentApprovalItem, RunEvent, RunState

from .test_assessment import policy, site
from .test_controller import FakePlanner, FakeRuntime, FakeVerifier


def setup_service(tmp_path, *, source=PlanSource.MODEL):
    runtime, verifier, planner = FakeRuntime(), FakeVerifier(), FakePlanner()
    runtime.sites = {"pantry-a": site()}
    runtime.manifest = {"pantry-a": {"name": "Pantry"}}
    original_propose = planner.propose

    def propose(*args, **kwargs):
        proposed = original_propose(*args, **kwargs)
        return ProposedPlan(proposed.plan, source)

    planner.propose = propose
    service = RealRepairService(
        FileRunStore(tmp_path / "runs"),
        FileEventSink(tmp_path / "runs"),
        FileRecipeStore(tmp_path / "recipes"),
        runtime=runtime,
        verifier=verifier,
        planner_factory=lambda: planner,
    )
    service._policy = policy()
    return service, runtime, verifier, planner


async def approve(service):
    assessment = await service.assess("pantry-a")
    return await service.approve(
        [
            AssessmentApprovalItem(
                assessment_id=assessment.assessment_id,
                fingerprint=assessment.fingerprint,
            )
        ],
        assessment.policy_revision,
        "session-one",
    )


@pytest.mark.asyncio
async def test_server_owned_assessment_and_session_bound_approval(tmp_path):
    service, runtime, _, _ = setup_service(tmp_path)
    approval = await approve(service)
    assert approval.site_ids == ["pantry-a"]
    with pytest.raises(LookupError):
        await service.get_approval(approval.approval_id, "different-session")
    with pytest.raises(LookupError):
        await service.get_approval("fabricated", "session-one")
    with pytest.raises(ValueError):
        await service.approve([], service._policy.revision, "session-one")
    runtime.current = replace(runtime.current, configuration_hash="drift")
    result = await service.run(approval, run_id="drift-run")
    assert result.state == RunState.BLOCKED
    assert runtime.activation_count == 0
    assert result.changes == []
    assert result.security_results["liveVerified"] is False


@pytest.mark.asyncio
async def test_real_coordinator_persists_complete_activation_checkpoint_and_recipe(
    tmp_path,
):
    service, runtime, _, planner = setup_service(tmp_path)
    approval = await approve(service)
    await service.event_sink.append_event(
        "run-1",
        RunEvent(sequence=1, timestamp="now", state=RunState.QUEUED, message="Queued"),
    )
    original_activate = runtime.activate

    def activate(target, candidate, original, *, timeout_s):
        # Read the on-disk checkpoint inside the side effect, not after the run.
        import json

        record = json.loads((tmp_path / "runs/run-1/run.json").read_text())
        assert record["checkpoint"]["state"] == "ACTIVATING"
        assert record["evidenceComplete"] is False
        assert record["checkpoint"]["original"]["image_id"] == original.image_id
        assert (
            record["checkpoint"]["candidate"]["snapshot"]["image_id"]
            == candidate.snapshot.image_id
        )
        assert record["checkpoint"]["approval"]["assessment_fingerprint"]
        return original_activate(target, candidate, original, timeout_s=timeout_s)

    runtime.activate = activate
    result = await service.run(approval, run_id="run-1")
    assert result.state == RunState.VERIFIED
    assert result.evidence_complete
    assert result.security_results["liveVerified"] is True
    events, _ = await service.event_sink.get_events("run-1", limit=1000)
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert len(list((tmp_path / "recipes").glob("*.json"))) == 1
    # Repeating an equivalent vulnerable deployment must reuse a verified recipe.
    from .test_controller import FakeRuntime

    runtime.current = FakeRuntime().current
    approval = await approve(service)
    result = await service.run(approval, run_id="run-2")
    assert result.plan_source.value == "VERIFIED_RECIPE"
    assert planner.calls == 1


@pytest.mark.asyncio
async def test_journal_failure_blocks_activation_and_recipe_learning(tmp_path):
    service, runtime, _, _ = setup_service(tmp_path)
    approval = await approve(service)
    original_save = service.run_store.save_run

    async def fail_intent(record):
        if record.state == RunState.ACTIVATING:
            raise OSError("disk full")
        await original_save(record)

    service.run_store.save_run = fail_intent
    result = await service.run(approval, run_id="run-disk-failure")
    assert result.state == RunState.BLOCKED
    assert not result.evidence_complete
    assert runtime.activation_count == 0
    assert not list((tmp_path / "recipes").glob("*.json"))


@pytest.mark.asyncio
async def test_simulation_never_learns_verified_recipe(tmp_path):
    service, _, _, _ = setup_service(tmp_path, source=PlanSource.TEST_DOUBLE)
    result = await service.run(await approve(service), run_id="test-double")
    assert result.state == RunState.VERIFIED
    assert not list((tmp_path / "recipes").glob("*.json"))


@pytest.mark.asyncio
async def test_missing_recovery_checkpoint_blocks_further_work(tmp_path):
    from patchpilot.shared.contracts import RunRecord

    service, _, _, _ = setup_service(tmp_path)
    result = await service.recover_interrupted(
        RunRecord(run_id="lost-checkpoint", state=RunState.ACTIVATING)
    )
    assert result.state == RunState.RECOVERY_FAILED
    with pytest.raises(RuntimeError):
        await service.assess("pantry-a")


@pytest.mark.asyncio
async def test_queued_interruption_has_no_runtime_side_effects(tmp_path):
    from patchpilot.shared.contracts import RunRecord

    service, runtime, _, _ = setup_service(tmp_path)
    result = await service.recover_interrupted(RunRecord(run_id="queued-only"))
    assert result.state == RunState.INTERRUPTED
    assert result.evidence_complete
    assert runtime.activation_count == 0
    assert (await service.assess("pantry-a")).can_repair


@pytest.mark.asyncio
async def test_recovery_replaces_success_claim_with_verified_unpatched_original(
    tmp_path,
):
    service, runtime, _, _ = setup_service(tmp_path)
    record = await service.run(await approve(service), run_id="interrupted-activation")
    assert record.security_results["liveVerified"]
    recovered = await service.recover_interrupted(record)
    assert recovered.state == RunState.RESTORED
    assert recovered.evidence_complete
    assert not recovered.security_results["liveVerified"]
    assert recovered.changes == []
    assert recovered.site_results["pantry-a"]["state"] == "RESTORED"
    assert runtime.current.php_version == "8.3.35"
