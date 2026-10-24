"""Real Docker activation and restoration acceptance for normalized core ports."""

from dataclasses import replace

import pytest

from patchpilot.core.domain import checks_complete
from patchpilot.core.policy import ConfigurationProfile, RepairPlan, ValidatedPlan
from patchpilot.runtime.bridge import HttpVerifier

pytestmark = pytest.mark.docker


@pytest.mark.parametrize(
    "site_id,profile",
    [("pantry-b", "preserve_basic"), ("clinic-b", "preserve_uploads")],
)
def test_real_bridge_activation_rechecks_identical_content_and_restores(
    isolated_runtime, site_id, profile
):
    runtime = isolated_runtime
    assert all(19000 <= entry["port"] < 29000 for entry in runtime.manifest.values())
    digest = runtime._patched_digest
    site = next(site for key, site in runtime.sites.items() if key.endswith(site_id))
    original = runtime.inspect(site, timeout_s=15)
    settings = ConfigurationProfile(
        profile,
        "8M" if profile == "preserve_uploads" else "2M",
        "10M" if profile == "preserve_uploads" else "8M",
    )
    plan = ValidatedPlan(RepairPlan("php83_patched", profile), digest, settings)
    verifier = HttpVerifier(runtime)
    candidate = None
    activation_started = False
    try:
        candidate = runtime.stage(site, plan, "bridge-acceptance", 1, timeout_s=60)
        assert runtime.inspect(site, timeout_s=15) == original
        assert candidate.snapshot.application_hash == original.application_hash
        assert checks_complete(
            site, verifier.check(site, candidate.snapshot, "STAGING", timeout_s=45)
        )
        activation_started = True
        live = runtime.activate(site, candidate, original, timeout_s=30)
        assert live == replace(candidate.snapshot, base_url=site.base_url)
        assert live.deployment_id == candidate.snapshot.deployment_id
        assert live.image_id == candidate.snapshot.image_id
        assert checks_complete(site, verifier.check(site, live, "LIVE", timeout_s=45))
    finally:
        if activation_started:
            restored = runtime.restore(site, original, timeout_s=30)
            assert restored == original
            assert checks_complete(
                site, verifier.check(site, restored, "RESTORATION", timeout_s=45)
            )
        runtime.cleanup(site, "bridge-acceptance", 1, timeout_s=15)


def test_real_upload_rejection_keeps_original_serving(isolated_runtime):
    runtime = isolated_runtime
    site = next(site for key, site in runtime.sites.items() if key.endswith("clinic-a"))
    original = runtime.inspect(site, timeout_s=15)
    plan = ValidatedPlan(
        RepairPlan("php83_patched", "preserve_basic"),
        runtime._patched_digest,
        ConfigurationProfile("preserve_basic", "2M", "8M"),
    )
    try:
        candidate = runtime.stage(site, plan, "bridge-rejected", 1, timeout_s=60)
        checks = HttpVerifier(runtime).check(
            site, candidate.snapshot, "STAGING", timeout_s=45
        )
        assert not checks_complete(site, checks)
        assert (
            next(check for check in checks if check.check_id == "upload_size").passed
            is False
        )
        assert runtime.inspect(site, timeout_s=15) == original
    finally:
        runtime.cleanup(site, "bridge-rejected", 1, timeout_s=15)


def test_real_activation_failure_restores_retained_files_and_serving_identity(
    isolated_runtime, monkeypatch
):
    runtime = isolated_runtime
    site = next(site for key, site in runtime.sites.items() if key.endswith("pantry-a"))
    original = runtime.inspect(site, timeout_s=15)
    plan = ValidatedPlan(
        RepairPlan("php83_patched", "preserve_basic"),
        runtime._patched_digest,
        ConfigurationProfile("preserve_basic", "2M", "8M"),
    )
    candidate = runtime.stage(site, plan, "bridge-activation-failure", 1, timeout_s=60)
    launch = runtime._launch

    def failed_launch(*args, **kwargs):
        raise RuntimeError("Injected failure after original retention")

    monkeypatch.setattr(runtime, "_launch", failed_launch)
    try:
        with pytest.raises(RuntimeError, match="Injected failure"):
            runtime.activate(site, candidate, original, timeout_s=30)
        restored = runtime.restore(site, original, timeout_s=30)
        assert restored == original
        assert checks_complete(
            site,
            HttpVerifier(runtime).check(site, restored, "RESTORATION", timeout_s=45),
        )
    finally:
        monkeypatch.setattr(runtime, "_launch", launch)
        runtime.cleanup(site, "bridge-activation-failure", 1, timeout_s=15)


def test_real_prepare_preserves_completed_records_and_recipe_memory(isolated_runtime):
    runtime = isolated_runtime
    record = runtime.workspace_root / "var" / "runs" / "completed-run" / "run.json"
    recipe = runtime.workspace_root / "var" / "recipes" / "verified-recipe.json"
    record.parent.mkdir(parents=True)
    recipe.parent.mkdir(parents=True)
    record.write_text('{"state":"VERIFIED"}')
    recipe.write_text('{"liveVerified":true}')
    report = runtime.prepare(timeout_s=240)
    assert report["status"] == "COMPLETED"
    assert report["recipes_cleared"] is False
    assert record.read_text() == '{"state":"VERIFIED"}'
    assert recipe.read_text() == '{"liveVerified":true}'
