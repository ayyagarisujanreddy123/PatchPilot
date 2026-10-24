"""Real application coordinator: server-owned approvals and durable core execution.

The HTTP layer owns admission/serialization. Blocking Docker/model work runs in a
thread; its journal waits for the async stores before permitting activation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import dotenv_values

from patchpilot.core.assessment import assess
from patchpilot.core.controller import RepairController
from patchpilot.core.domain import DeploymentSnapshot, checks_complete
from patchpilot.core.planner import AnthropicPlanner
from patchpilot.core.policy import RepairPlan, load_policy
from patchpilot.core.ports import Approval, PlanSource, ProposedPlan, RunEvent
from patchpilot.shared import contracts as api


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check(check) -> api.CheckResult:
    return api.CheckResult(
        check_id=check.check_id,
        site_id=check.site_id,
        phase=check.phase,
        passed=check.passed,
        message=check.message,
        duration_ms=round(check.duration_ms) if check.duration_ms is not None else None,
        expected_value=check.expected,
        observed_value=check.observed,
    )


def _provenance(proposed) -> dict[str, Any]:
    return {
        "source": proposed.source.value,
        "modelId": proposed.model_id,
        "providerMessageId": proposed.provider_message_id,
        "inputTokens": proposed.input_tokens,
        "outputTokens": proposed.output_tokens,
        "plan": {
            "targetImageAlias": proposed.plan.target_image_alias,
            "configProfileId": proposed.plan.config_profile_id,
            "rationale": proposed.plan.rationale,
        },
    }


def _compatibility(context) -> str:
    value = {
        "template": context.site.template_revision,
        "capabilities": sorted(context.site.capabilities),
        "verifier": context.site.verifier_revision,
        "application": context.original.application_hash,
        "configuration": context.original.configuration_hash,
        "php": context.original.php_version,
        "sapi": context.original.sapi,
        "mitigation": context.original.upload_progress_enabled,
        "policy": asdict(context.policy),
    }
    value["policy"].pop("registered_site_ids")
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class _MemoryPlanner:
    def __init__(self, service, loop, delegate, enabled):
        self.service, self.loop, self.delegate, self.enabled = (
            service,
            loop,
            delegate,
            enabled,
        )

    def propose(self, context, failures, *, timeout_s):
        if self.enabled and not failures:
            recipe = asyncio.run_coroutine_threadsafe(
                self.service.recipe_store.find_matching(_compatibility(context)),
                self.loop,
            ).result(timeout=timeout_s)
            if recipe and recipe.verification_evidence.get("liveVerified") is True:
                plan = RepairPlan(
                    recipe.successful_plan.target_image_alias,
                    recipe.successful_plan.configuration_profile_id,
                    recipe.successful_plan.rationale,
                )
                context.policy.validate_plan(context.site.site_id, plan)
                return ProposedPlan(plan, PlanSource.VERIFIED_RECIPE)
        return self.delegate.propose(context, failures, timeout_s=timeout_s)


class _Journal:
    def __init__(self, service, loop, record, completed_checks, more_sites):
        self.service, self.loop, self.record = service, loop, record
        self.completed_checks, self.more_sites = completed_checks, more_sites
        self.last_event = None

    def emit(self, event: RunEvent) -> None:
        self.last_event = event
        # No timeout: persistence must finish (or fail) before any side effect.
        asyncio.run_coroutine_threadsafe(self._persist(event), self.loop).result()

    async def _persist(self, event):
        record = self.record
        record.current_site_id, record.attempt = event.site_id, event.attempt
        record.checkpoint = json.loads(
            json.dumps(
                asdict(event),
                default=lambda value: (
                    value.isoformat() if isinstance(value, datetime) else sorted(value)
                ),
            )
        )
        record.state = api.RunState(event.state.value)
        if self.more_sites and event.state.value == "VERIFIED":
            record.state = api.RunState.ASSESSING
        record.checks = self.completed_checks + [
            _check(check) for check in event.checks
        ]
        record.warnings = list(event.warnings)
        # Append and cleanup still follow this snapshot; completion is separate.
        record.evidence_complete = False
        record.updated_at = _now()
        if event.original:
            record.original_identity = asdict(event.original)
        if event.candidate:
            record.candidate_identity = asdict(event.candidate.snapshot)
        if event.plan:
            record.plan_source = api.PlanSource(event.plan.source.value)
            record.provenance = _provenance(event.plan)
        await self.service.run_store.save_run(record)
        self.service._sequence += 1
        await self.service.event_sink.append_event(
            record.run_id,
            api.RunEvent(
                sequence=self.service._sequence,
                timestamp=_now(),
                site_id=event.site_id,
                state=api.RunState(event.state.value),
                message=event.message,
            ),
        )


class RealRepairService:
    """Composition boundary; never discovers targets from untrusted URLs."""

    def __init__(
        self,
        run_store,
        event_sink,
        recipe_store,
        *,
        runtime=None,
        verifier=None,
        planner_factory=None,
        workspace_root=None,
    ):
        self.root = Path(workspace_root or Path(__file__).resolve().parents[3])
        if runtime is None:
            from patchpilot.runtime.bridge import DockerRuntime, HttpVerifier

            runtime = DockerRuntime(workspace_root=self.root)
            verifier = HttpVerifier(runtime)
        self.runtime, self.verifier = runtime, verifier
        self.run_store, self.event_sink, self.recipe_store = (
            run_store,
            event_sink,
            recipe_store,
        )
        self.planner_factory = planner_factory or (
            lambda: AnthropicPlanner.from_environment(env_file=self.root / ".env")
        )
        self._policy = None
        self._assessments: dict[str, tuple[api.Assessment, Any, Any, Any]] = {}
        self._approvals: dict[str, tuple[api.Approval, dict[str, Approval]]] = {}
        self._sequence = 0
        self._recovery_failed = False
        self._latest: dict[str, tuple[str, str | None]] = {}

    async def list_sites(self):
        return [
            api.SiteManifest(
                site_id=site.site_id,
                display_name=self.runtime.manifest[site.site_id]["name"],
                base_url=site.base_url,
                capabilities=sorted(site.capabilities),
                template_revision=site.template_revision,
                assessment_state=self._latest.get(site.site_id, ("UNASSESSED", None))[
                    0
                ],
                last_run_id=self._latest.get(site.site_id, ("UNASSESSED", None))[1],
            )
            for site in self.runtime.sites.values()
        ]

    async def health(self):
        def docker_available():
            if not shutil.which("docker"):
                return False
            try:
                return (
                    subprocess.run(
                        ["docker", "info", "--format", "{{.ServerVersion}}"],
                        capture_output=True,
                        timeout=3,
                        check=False,
                    ).returncode
                    == 0
                )
            except (OSError, subprocess.TimeoutExpired):
                return False

        docker = await asyncio.to_thread(docker_available)
        local = dotenv_values(self.root / ".env", interpolate=False)
        key = os.environ.get("ANTHROPIC_API_KEY") or local.get("ANTHROPIC_API_KEY")
        configured = bool(key and key.strip() and key != "your-anthropic-api-key-here")
        ready = (
            docker
            and configured
            and self._policy is not None
            and not self._recovery_failed
        )
        return {
            "mode": "REAL",
            "ready": ready,
            "dockerAvailable": docker,
            "plannerConfigured": configured,
            "prepared": self._policy is not None,
            "message": "Ready for registered PHP fixtures"
            if ready
            else "Start Docker, configure Anthropic, and prepare the registered fixtures."
            if not self._recovery_failed
            else "Recovery needs human attention; repair is blocked.",
        }

    async def prepare(self):
        if self._recovery_failed:
            raise RuntimeError(
                "Resolve the unverified deployment recovery before preparing fixtures"
            )
        # Resolve trusted immutable policy first; no model-controlled image references.
        try:
            digest = await asyncio.to_thread(
                self.runtime.resolve_patched_digest, timeout_s=180
            )
            self._policy = load_policy(
                self.root / "config/advisories.json",
                registered_site_ids=frozenset(self.runtime.sites),
                approved_image_digest=digest,
            )
            report = await asyncio.to_thread(self.runtime.prepare, timeout_s=240)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            self._policy = None
            raise RuntimeError(
                "Fixture preparation failed; check the Docker runtime"
            ) from None
        self._assessments.clear()
        self._approvals.clear()
        self._latest.clear()
        return {"state": "COMPLETED", "imageDigest": digest, "runtime": report}

    async def reset(self, clear_recipes=False):
        report = await self.prepare()
        report["clearedRecipes"] = (
            await self.recipe_store.clear_recipes() if clear_recipes else 0
        )
        return report

    async def assess(self, site_id):
        if site_id not in self.runtime.sites:
            raise LookupError("Only registered local fixture URLs are supported")
        if self._policy is None or self._recovery_failed:
            raise RuntimeError("Prepare the registered PHP fixtures before assessment")
        site = self.runtime.sites[site_id]
        try:
            snapshot = await asyncio.to_thread(self.runtime.inspect, site, timeout_s=15)
            checks = await asyncio.to_thread(
                self.verifier.check, site, snapshot, "BASELINE", timeout_s=45
            )
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            raise RuntimeError(
                "The registered fixture could not be inspected; prepare the fixtures"
            ) from None
        result = assess(site, snapshot, checks, self._policy)
        changes = []
        if result.runtime_update_needed:
            changes.append(
                f"Update PHP {snapshot.php_version} to {self._policy.fixed_version}"
            )
        if result.mitigation_needed:
            changes.append("Disable session.upload_progress.enabled")
        response = api.Assessment(
            assessment_id="assessment-" + uuid4().hex,
            site_id=site_id,
            fingerprint=result.fingerprint,
            policy_revision=self._policy.revision,
            applicability=result.applicability.value,
            current_runtime={
                "phpVersion": snapshot.php_version,
                "sapi": snapshot.sapi,
                "uploadProgressEnabled": snapshot.upload_progress_enabled,
                "deploymentId": snapshot.deployment_id,
                "imageId": snapshot.image_id,
                "applicationHash": snapshot.application_hash,
                "configurationHash": snapshot.configuration_hash,
                "baseUrl": snapshot.base_url,
            },
            proposed_changes=changes,
            required_checks=sorted(site.required_checks),
            can_repair=result.can_repair,
            blocked_reason=result.blocked_reason,
        )
        self._assessments[response.assessment_id] = (response, site, snapshot, checks)
        self._latest[site_id] = (
            result.applicability.value,
            self._latest.get(site_id, ("", None))[1],
        )
        return response

    async def approve(self, items, policy_revision, operator_session):
        if not items or len(items) > len(self.runtime.sites) or self._policy is None:
            raise ValueError("Select one or more current, repairable assessments")
        if policy_revision != self._policy.revision or not operator_session:
            raise ValueError("Approval policy or operator session is invalid")
        expiry = datetime.now(UTC) + timedelta(minutes=30)
        approval_id = "approval-" + uuid4().hex
        per_site = {}
        for item in items:
            entry = self._assessments.get(item.assessment_id)
            if entry is None:
                raise LookupError("Assessment does not exist; assess the site again")
            response, site, _, _ = entry
            if (
                response.fingerprint != item.fingerprint
                or not response.can_repair
                or response.policy_revision != policy_revision
                or site.site_id in per_site
            ):
                raise ValueError("Approval must match distinct, repairable assessments")
            per_site[site.site_id] = Approval(
                approval_id,
                site.site_id,
                policy_revision,
                response.fingerprint,
                expiry,
                self._policy.target_image_alias,
                frozenset(profile.profile_id for profile in self._policy.profiles),
            )
        response = api.Approval(
            approval_id=approval_id,
            site_ids=list(per_site),
            assessments=items,
            policy_revision=policy_revision,
            expires_at=expiry.isoformat(),
            operator_session=operator_session,
            permitted_changes=["Approved PHP image and configuration profiles"],
            recovery_authority=True,
        )
        self._approvals[approval_id] = (response, per_site)
        return response

    async def get_approval(self, approval_id, operator_session):
        entry = self._approvals.get(approval_id)
        if entry is None or entry[0].operator_session != operator_session:
            raise LookupError("Approval does not exist for this session")
        if datetime.fromisoformat(entry[0].expires_at) <= datetime.now(UTC):
            raise ValueError("Approval expired; assess and approve again")
        return entry[0]

    async def run(self, approval, memory_enabled=True, *, run_id, target_outcome=None):
        # HTTP input cannot inject a simulated outcome into real execution.
        if target_outcome not in (None, "verified"):
            raise ValueError("Simulated outcomes are unavailable in real mode")
        trusted = await self.get_approval(
            approval.approval_id, approval.operator_session
        )
        per_site = self._approvals[trusted.approval_id][1]
        if self._policy is None or self._recovery_failed:
            raise RuntimeError("The real runtime is not ready")
        record = await self.run_store.get_run(run_id) or api.RunRecord(run_id=run_id)
        record.site_ids, record.approval_id = list(per_site), trusted.approval_id
        record.started_at, record.site_results = _now(), {}
        _, self._sequence = await self.event_sink.get_events(run_id, limit=1000)
        loop, all_checks = asyncio.get_running_loop(), []
        planner = self.planner_factory()
        try:
            for index, (site_id, bound_approval) in enumerate(per_site.items()):
                journal = _Journal(
                    self, loop, record, all_checks, index < len(per_site) - 1
                )
                controller = RepairController(
                    self._policy,
                    self.runtime,
                    self.verifier,
                    _MemoryPlanner(self, loop, planner, memory_enabled),
                    journal,
                )
                result = await asyncio.to_thread(
                    controller.run,
                    self.runtime.sites[site_id],
                    bound_approval,
                    run_id=run_id,
                )
                converted = [_check(check) for check in result.checks]
                all_checks.extend(converted)
                record.site_results[site_id] = {
                    "state": result.state.value,
                    "planSource": result.plan_source,
                    "original": asdict(result.original) if result.original else None,
                    "final": asdict(result.final) if result.final else None,
                    "error": result.error,
                    "evidenceComplete": result.evidence_complete,
                    "checks": [item.model_dump(by_alias=True) for item in converted],
                    "provenance": _provenance(journal.last_event.plan)
                    if journal.last_event and journal.last_event.plan
                    else {},
                }
                record.state = api.RunState(result.state.value)
                self._latest[site_id] = (result.state.value, run_id)
                record.evidence_complete = result.evidence_complete
                record.error, record.warnings = result.error, list(result.warnings)
                if result.state.value == "VERIFIED" and index < len(per_site) - 1:
                    record.state = api.RunState.ASSESSING
                    record.evidence_complete = False
                record.checks = list(all_checks)
                # A recipe may use only a site's durably completed proof.
                await self.run_store.save_run(record)
                if result.state.value != "VERIFIED" or not result.evidence_complete:
                    if result.state.value == "RECOVERY_FAILED":
                        self._recovery_failed = True
                    break
                if memory_enabled and journal.last_event and journal.last_event.plan:
                    try:
                        await self._learn(site_id, result, journal.last_event, run_id)
                    except (OSError, ValueError):
                        record.warnings.append(
                            "Verified repair recipe could not be saved"
                        )
        finally:
            close = getattr(planner, "close", None)
            if close:
                await asyncio.to_thread(close)
        record.checks, record.finished_at, record.updated_at = (
            all_checks,
            _now(),
            _now(),
        )
        verified = len(record.site_results) == len(per_site) and all(
            item["state"] == "VERIFIED" and item["evidenceComplete"]
            for item in record.site_results.values()
        )
        record.changes = (
            ["Approved PHP runtime image and configuration activated"]
            if verified
            else []
        )
        record.security_results = {
            "liveVerified": verified,
            "policyRevision": self._policy.revision,
            "fixedPhpVersion": self._policy.fixed_version,
            "evidenceComplete": record.evidence_complete,
            "scope": "Registered PHP runtime/configuration checks; no broad penetration test",
        }
        await self.run_store.save_run(record)
        return record

    async def _learn(self, site_id, result, event, run_id):
        from patchpilot.core.ports import PlanningContext

        site = self.runtime.sites[site_id]
        live = tuple(check for check in result.checks if check.phase == "LIVE")
        if not checks_complete(site, live) or result.plan_source not in (
            PlanSource.MODEL,
            PlanSource.VERIFIED_RECIPE,
        ):
            return
        context = PlanningContext(site, result.original, None, self._policy)
        plan = event.plan.plan
        await self.recipe_store.save_recipe(
            api.Recipe(
                recipe_id="recipe-" + uuid4().hex,
                compatibility_key=_compatibility(context),
                successful_plan=api.RepairPlan(
                    target_image_alias=plan.target_image_alias,
                    configuration_profile_id=plan.config_profile_id,
                    rationale=plan.rationale,
                ),
                originating_run_id=run_id,
                originating_site_id=site_id,
                verification_evidence={
                    "liveVerified": True,
                    "checks": [_check(c).model_dump(by_alias=True) for c in live],
                },
                verified_at=_now(),
            )
        )

    async def recover_interrupted(self, record):
        checkpoint = record.checkpoint or {}
        site_id, raw = checkpoint.get("site_id"), checkpoint.get("original")
        record.evidence_complete = False
        if not raw and (
            record.state == api.RunState.QUEUED
            or checkpoint.get("state") in {"QUEUED", "ASSESSING"}
        ):
            record.state = api.RunState.INTERRUPTED
            record.error = (
                "Interrupted before deployment changes; assess and approve again"
            )
            record.evidence_complete = True
            record.finished_at, record.updated_at = _now(), _now()
            await self.run_store.save_run(record)
            return record
        try:
            if site_id not in self.runtime.sites or not raw:
                raise ValueError("No durable original checkpoint")
            site, original = self.runtime.sites[site_id], DeploymentSnapshot(**raw)
            state = checkpoint.get("state")
            if state in {"ACTIVATING", "LIVE_VERIFYING", "RESTORING", "VERIFIED"}:
                restored = await asyncio.to_thread(
                    self.runtime.restore, site, original, timeout_s=30
                )
            else:
                restored = await asyncio.to_thread(
                    self.runtime.inspect, site, timeout_s=15
                )
            checks = await asyncio.to_thread(
                self.verifier.check, site, restored, "RESTORATION", timeout_s=45
            )
            if restored != original or not checks_complete(site, checks):
                raise ValueError("Original recovery did not pass verification")
            await asyncio.to_thread(
                self.runtime.cleanup,
                site,
                record.run_id,
                checkpoint.get("attempt", 1),
                timeout_s=15,
            )
            record.checks.extend(_check(check) for check in checks)
            record.state = api.RunState.RESTORED
            record.error = "Interrupted run recovered; original remains unpatched"
            record.evidence_complete = True
            record.site_results = record.site_results or {}
            record.site_results[site_id] = {
                "state": "RESTORED",
                "final": asdict(original),
                "evidenceComplete": True,
                "checks": [_check(check).model_dump(by_alias=True) for check in checks],
            }
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            record.state = api.RunState.RECOVERY_FAILED
            record.error = "Interrupted deployment could not be verified; human recovery is required"
            self._recovery_failed = True
        if site_id in self.runtime.sites:
            self._latest[site_id] = (record.state.value, record.run_id)
        record.changes = []
        record.security_results = {
            "liveVerified": False,
            "scope": "Interrupted repair; restoration does not patch the original",
        }
        record.finished_at, record.updated_at = _now(), _now()
        await self.run_store.save_run(record)
        return record

    async def close(self):
        return None
