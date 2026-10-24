"""Exercise repair outcomes with private, stateful adapter fakes."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from patchpilot.core.assessment import assess
from patchpilot.core.controller import RepairController
from patchpilot.core.domain import CheckResult
from patchpilot.core.policy import RepairPlan
from patchpilot.core.ports import (
    Approval,
    Candidate,
    PlanSource,
    ProposedPlan,
    RunState,
)

from .test_assessment import original, passing_checks, policy, site

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


class FakeRuntime:
    def __init__(self):
        self.current = replace(original(), base_url=site().base_url)
        self.staging = set()
        self.activation_count = 0
        self.fail_activation = False
        self.fail_restore = False
        self.fail_stage = False

    def inspect(self, target, *, timeout_s):
        return self.current

    def stage(self, target, plan, run_id, attempt, *, timeout_s):
        handle = f"{run_id}-{attempt}"
        self.staging.add(handle)
        if self.fail_stage:
            raise RuntimeError("SECRET_NOT_FOR_OUTPUT")
        snapshot = replace(
            self.current,
            deployment_id=handle,
            image_id="sha256:" + "d" * 64,
            configuration_hash=plan.profile.profile_id,
            php_version="8.3.36",
            upload_progress_enabled=False,
            base_image_digest=plan.image_digest,
            base_url="http://127.0.0.1:19001",
        )
        return Candidate(handle, snapshot)

    def activate(self, target, candidate, retained, *, timeout_s):
        self.activation_count += 1
        self.current = None
        if self.fail_activation:
            raise RuntimeError("SECRET_NOT_FOR_OUTPUT")
        self.current = replace(candidate.snapshot, base_url=target.base_url)
        return self.current

    def restore(self, target, retained, *, timeout_s):
        if self.fail_restore:
            raise RuntimeError("SECRET_NOT_FOR_OUTPUT")
        self.current = retained
        return retained

    def cleanup(self, target, run_id, attempt, *, timeout_s):
        self.staging.discard(f"{run_id}-{attempt}")


class FakeVerifier:
    def __init__(self):
        self.failed_staging_remaining = 0
        self.fail_live = False

    def check(self, target, snapshot, phase, *, timeout_s):
        checks = passing_checks(target)
        should_fail = phase == "LIVE" and self.fail_live
        if phase == "STAGING" and self.failed_staging_remaining:
            self.failed_staging_remaining -= 1
            should_fail = True
        if should_fail:
            checks = (
                *checks,
                CheckResult("compatibility", False, "Required behavior failed"),
            )
        return checks


class FakePlanner:
    def __init__(self):
        self.calls = 0
        self.failures = []
        self.plan = RepairPlan("php83_patched", "preserve_basic")

    def propose(self, context, failures, *, timeout_s):
        self.calls += 1
        self.failures.append(failures)
        return ProposedPlan(self.plan, PlanSource.TEST_DOUBLE)


class FakeJournal:
    def __init__(self):
        self.events = []
        self.fail_state = None

    def emit(self, event):
        if event.state == self.fail_state:
            raise RuntimeError("SECRET_NOT_FOR_OUTPUT")
        self.events.append(event)


def setup_run():
    target = site()
    current_policy = policy()
    runtime = FakeRuntime()
    verifier = FakeVerifier()
    planner = FakePlanner()
    journal = FakeJournal()
    assessment = assess(target, runtime.current, passing_checks(), current_policy)
    approval = Approval(
        "approval-1",
        target.site_id,
        current_policy.revision,
        assessment.fingerprint,
        NOW + timedelta(minutes=20),
        current_policy.target_image_alias,
        frozenset({"preserve_basic", "preserve_uploads"}),
    )
    controller = RepairController(
        current_policy, runtime, verifier, planner, journal, now=lambda: NOW
    )
    return controller, target, approval, runtime, verifier, planner, journal


def test_success_requires_live_checks_and_preserves_the_tested_identity():
    controller, target, approval, runtime, _, planner, journal = setup_run()

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.VERIFIED
    assert result.attempts == 1
    assert result.plan_source is PlanSource.TEST_DOUBLE
    assert runtime.current.php_version == "8.3.36"
    assert runtime.current.base_url == target.base_url
    assert runtime.staging == set()
    assert planner.calls == 1
    assert {"BASELINE", "STAGING", "LIVE"} <= {check.phase for check in result.checks}
    activation = next(
        event for event in journal.events if event.state is RunState.ACTIVATING
    )
    assert activation.original is not None and activation.candidate is not None
    assert journal.events[-1].state is RunState.VERIFIED


def test_expired_approval_is_blocked_without_planning_or_activation():
    controller, target, approval, runtime, _, planner, _ = setup_run()

    result = controller.run(
        target, replace(approval, expires_at=NOW - timedelta(seconds=1)), run_id="run-1"
    )

    assert result.state is RunState.BLOCKED
    assert planner.calls == runtime.activation_count == 0
    assert runtime.current.deployment_id == "original"


def test_changed_assessment_fingerprint_requires_fresh_approval():
    controller, target, approval, runtime, _, planner, _ = setup_run()
    runtime.current = replace(
        runtime.current, configuration_hash="changed-after-review"
    )

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert planner.calls == runtime.activation_count == 0


def test_unapproved_model_plan_cannot_reach_activation():
    controller, target, approval, runtime, _, planner, _ = setup_run()
    planner.plan = RepairPlan("php83_patched", "not_registered")

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert runtime.activation_count == 0
    assert runtime.staging == set()


def test_failed_candidate_is_revised_once_with_real_failure_evidence():
    controller, target, approval, runtime, verifier, planner, journal = setup_run()
    verifier.failed_staging_remaining = 1

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.VERIFIED
    assert result.attempts == planner.calls == 2
    assert any(check.passed is False for check in planner.failures[1])
    assert runtime.activation_count == 1
    assert runtime.staging == set()
    staging_intents = [
        event for event in journal.events if event.state is RunState.STAGING
    ]
    assert all(event.candidate is None for event in staging_intents)


def test_two_failed_candidates_leave_the_original_serving():
    controller, target, approval, runtime, verifier, planner, _ = setup_run()
    verifier.failed_staging_remaining = 10

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.REJECTED
    assert result.attempts == planner.calls == 2
    assert runtime.activation_count == 0
    assert runtime.current.deployment_id == "original"
    assert runtime.staging == set()


def test_activation_failure_restores_and_verifies_the_retained_original():
    controller, target, approval, runtime, _, _, _ = setup_run()
    retained = runtime.current
    runtime.fail_activation = True

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.RESTORED
    assert result.final == retained == runtime.current
    assert runtime.current.php_version == "8.3.35"
    assert any(check.phase == "RESTORATION" for check in result.checks)
    assert runtime.staging == set()


def test_failed_live_check_cannot_be_reported_as_verified():
    controller, target, approval, runtime, verifier, _, _ = setup_run()
    verifier.fail_live = True

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.RESTORED
    assert runtime.current.deployment_id == "original"


def test_failed_restoration_is_reported_without_a_verified_final_snapshot():
    controller, target, approval, runtime, _, _, _ = setup_run()
    runtime.fail_activation = runtime.fail_restore = True

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.RECOVERY_FAILED
    assert result.final is None
    assert result.original.deployment_id == "original"
    assert runtime.staging == set()


def test_journal_failure_before_activation_prevents_live_changes():
    controller, target, approval, runtime, _, _, journal = setup_run()
    journal.fail_state = RunState.ACTIVATING

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert runtime.activation_count == 0
    assert runtime.current.deployment_id == "original"
    assert not result.evidence_complete
    assert runtime.staging == set()


def test_journal_failure_does_not_prevent_emergency_restoration():
    controller, target, approval, runtime, _, _, journal = setup_run()
    runtime.fail_activation = True
    journal.fail_state = RunState.RESTORING

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.RESTORED
    assert runtime.current.deployment_id == "original"
    assert not result.evidence_complete
    assert result.warnings


def test_partial_staging_failure_is_cleaned_and_adapter_secrets_are_not_exposed():
    controller, target, approval, runtime, _, _, journal = setup_run()
    runtime.fail_stage = True

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert runtime.current.deployment_id == "original"
    assert runtime.staging == set()
    assert "SECRET_NOT_FOR_OUTPUT" not in repr(result)
    assert "SECRET_NOT_FOR_OUTPUT" not in repr(journal.events)


def test_empty_verification_cannot_pass_and_trigger_activation():
    controller, target, approval, runtime, verifier, planner, _ = setup_run()
    normal_check = verifier.check
    verifier.check = lambda target, snapshot, phase, **options: (
        () if phase == "STAGING" else normal_check(target, snapshot, phase, **options)
    )

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.REJECTED
    assert planner.calls == 2
    assert runtime.activation_count == 0
    assert runtime.staging == set()


def test_live_content_drift_requires_restoration():
    controller, target, approval, runtime, _, _, _ = setup_run()
    activate = runtime.activate

    def mismatched_activation(*args, **kwargs):
        runtime.current = replace(
            activate(*args, **kwargs), application_hash="different-app"
        )
        return runtime.current

    runtime.activate = mismatched_activation

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.RESTORED
    assert runtime.current.application_hash == "app-v1"


def test_drift_while_staging_blocks_activation_and_requests_new_assessment():
    controller, target, approval, runtime, _, _, _ = setup_run()
    stage = runtime.stage

    def stage_with_drift(*args, **kwargs):
        candidate = stage(*args, **kwargs)
        runtime.current = replace(runtime.current, configuration_hash="external-change")
        return candidate

    runtime.stage = stage_with_drift

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert runtime.activation_count == 0
    assert runtime.current.configuration_hash == "external-change"


def test_cleanup_failure_is_visible_without_erasing_a_verified_live_repair():
    controller, target, approval, runtime, _, _, _ = setup_run()

    def fail_cleanup(*args, **kwargs):
        raise RuntimeError("SECRET_NOT_FOR_OUTPUT")

    runtime.cleanup = fail_cleanup

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.VERIFIED
    assert result.warnings
    assert "SECRET_NOT_FOR_OUTPUT" not in repr(result)


def test_candidate_cannot_alias_the_original_endpoint_with_a_trailing_slash():
    controller, target, approval, runtime, _, _, _ = setup_run()
    stage = runtime.stage

    def stage_on_original(*args, **kwargs):
        candidate = stage(*args, **kwargs)
        return replace(
            candidate,
            snapshot=replace(candidate.snapshot, base_url=target.base_url + "/"),
        )

    runtime.stage = stage_on_original

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert runtime.activation_count == 0
    assert runtime.staging == set()


def test_approval_expiry_during_intent_persistence_blocks_activation():
    controller, target, approval, runtime, _, _, journal = setup_run()
    current_time = [NOW]
    controller = replace(controller, now=lambda: current_time[0])
    normal_emit = journal.emit

    def slow_checkpoint(event):
        normal_emit(event)
        if event.state is RunState.ACTIVATING:
            current_time[0] = approval.expires_at + timedelta(seconds=1)

    journal.emit = slow_checkpoint

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert runtime.activation_count == 0
    assert runtime.current.deployment_id == "original"


def test_repair_deadline_stops_activation_but_still_attempts_scoped_cleanup():
    controller, target, approval, runtime, _, _, _ = setup_run()
    ticks = [0.0]
    controller = replace(controller, monotonic=lambda: ticks[0])
    stage = runtime.stage

    def slow_stage(*args, **kwargs):
        candidate = stage(*args, **kwargs)
        ticks[0] = 601.0
        return candidate

    runtime.stage = slow_stage

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert "deadline" in result.error.lower()
    assert runtime.activation_count == 0
    assert runtime.staging == set()


def test_missing_candidate_evidence_is_recorded_as_a_failed_gate():
    controller, target, approval, _, verifier, _, _ = setup_run()
    normal_check = verifier.check
    verifier.check = lambda target, snapshot, phase, **options: (
        () if phase == "STAGING" else normal_check(target, snapshot, phase, **options)
    )

    result = controller.run(target, approval, run_id="run-1")

    assert any(
        check.check_id == "candidate_gate"
        and check.passed is False
        and check.phase == "STAGING"
        for check in result.checks
    )


def test_planner_provenance_must_be_an_explicit_registered_source():
    controller, target, approval, runtime, _, planner, _ = setup_run()
    planner.propose = lambda *args, **kwargs: ProposedPlan(planner.plan, "MADE_UP")

    result = controller.run(target, approval, run_id="run-1")

    assert result.state is RunState.BLOCKED
    assert runtime.activation_count == 0


def test_malformed_planner_results_are_blocked_without_recording_raw_payloads():
    for malformed in (
        None,
        {"credential": "DO_NOT_RECORD_RAW_ADAPTER_DATA"},
        ProposedPlan(
            {"credential": "DO_NOT_RECORD_RAW_ADAPTER_DATA"}, PlanSource.MODEL
        ),
    ):
        controller, target, approval, runtime, _, planner, journal = setup_run()
        planner.propose = lambda *args, response=malformed, **kwargs: response

        result = controller.run(target, approval, run_id="run-1")

        assert result.state is RunState.BLOCKED
        assert runtime.activation_count == 0
        assert "DO_NOT_RECORD_RAW_ADAPTER_DATA" not in repr(journal.events)


def test_malformed_runtime_results_are_not_copied_into_run_evidence():
    for operation in ("inspect", "stage"):
        controller, target, approval, runtime, _, _, journal = setup_run()
        setattr(
            runtime,
            operation,
            lambda *args, **kwargs: {"credential": "DO_NOT_RECORD_RAW_ADAPTER_DATA"},
        )

        result = controller.run(target, approval, run_id="run-1")

        assert result.state is RunState.BLOCKED
        assert runtime.activation_count == 0
        assert "DO_NOT_RECORD_RAW_ADAPTER_DATA" not in repr(result)
        assert "DO_NOT_RECORD_RAW_ADAPTER_DATA" not in repr(journal.events)
