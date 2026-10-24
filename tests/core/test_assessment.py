"""Assessment distinguishes vulnerability findings from existing site failures."""

from dataclasses import replace

import pytest

from patchpilot.core.assessment import Applicability, assess
from patchpilot.core.domain import CheckResult, DeploymentSnapshot, Site
from patchpilot.core.policy import load_policy

from .test_policy import POLICY_FILE, REGISTERED_SITES, TEST_DIGEST


def original():
    return DeploymentSnapshot(
        site_id="pantry-a",
        deployment_id="original",
        image_id="sha256:" + "b" * 64,
        application_hash="app-v1",
        configuration_hash="config-v1",
        php_version="8.3.35",
        sapi="apache2handler",
        upload_progress_enabled=True,
    )


def site():
    return Site("pantry-a", "http://127.0.0.1:8081", "basic-v1")


def passing_checks(target=None):
    return tuple(CheckResult(key, True) for key in (target or site()).required_checks)


def policy():
    return load_policy(
        POLICY_FILE,
        registered_site_ids=REGISTERED_SITES,
        approved_image_digest=TEST_DIGEST,
    )


def test_supported_original_needs_both_update_and_mitigation():
    result = assess(site(), original(), passing_checks(), policy())

    assert result.applicability is Applicability.AFFECTED
    assert result.can_repair
    assert result.runtime_update_needed
    assert result.mitigation_needed
    assert len(result.fingerprint) == 64


def test_fixed_runtime_with_mitigation_is_not_reported_as_a_repair():
    snapshot = replace(original(), php_version="8.3.36", upload_progress_enabled=False)

    result = assess(site(), snapshot, passing_checks(), policy())

    assert result.applicability is Applicability.NOT_AFFECTED
    assert not result.can_repair
    assert not result.runtime_update_needed
    assert not result.mitigation_needed


def test_fixed_runtime_can_still_require_the_separate_mitigation():
    result = assess(
        site(), replace(original(), php_version="8.3.36"), passing_checks(), policy()
    )

    assert result.can_repair
    assert not result.runtime_update_needed
    assert result.mitigation_needed


@pytest.mark.parametrize(
    "changes",
    [
        {"php_version": "8.4.27"},
        {"php_version": "8.3.36-vendor1"},
        {"sapi": "cli"},
        {"site_id": "other-site"},
        {"php_version": "8.3.37"},
    ],
)
def test_unknown_environment_or_potential_downgrade_needs_help(changes):
    result = assess(site(), replace(original(), **changes), passing_checks(), policy())

    assert result.applicability is Applicability.UNSUPPORTED
    assert not result.can_repair
    assert result.blocked_reason


@pytest.mark.parametrize("checks", [(), (CheckResult("homepage", True),)])
def test_incomplete_baseline_never_passes_vacuously(checks):
    result = assess(site(), original(), checks, policy())

    assert result.applicability is Applicability.BASELINE_FAILED
    assert not result.can_repair


def test_failed_baseline_and_duplicate_checks_block_repair():
    failed = (*passing_checks(), CheckResult("existing_failure", False))
    duplicate = (*passing_checks(), CheckResult("homepage", True))

    for checks in (failed, duplicate):
        result = assess(site(), original(), checks, policy())
        assert result.applicability is Applicability.BASELINE_FAILED
        assert not result.can_repair


def test_upload_site_requires_size_and_hash_evidence():
    upload_site = replace(
        site(), capabilities=frozenset({"homepage", "contact", "upload"})
    )
    result = assess(upload_site, original(), passing_checks(), policy())

    assert result.applicability is Applicability.BASELINE_FAILED
    assert {"upload_size", "upload_hash"} <= upload_site.required_checks


def test_missing_image_pin_keeps_the_finding_but_blocks_execution():
    unresolved = load_policy(POLICY_FILE, registered_site_ids=REGISTERED_SITES)

    result = assess(site(), original(), passing_checks(), unresolved)

    assert result.applicability is Applicability.AFFECTED
    assert not result.can_repair
    assert "digest" in result.blocked_reason


def test_assessment_fingerprint_changes_when_deployment_policy_or_requirements_change():
    baseline = assess(site(), original(), passing_checks(), policy()).fingerprint
    observations = [
        (site(), replace(original(), configuration_hash="changed"), policy()),
        (site(), original(), replace(policy(), revision="new-policy")),
        (replace(site(), template_revision="new-template"), original(), policy()),
        (site(), original(), replace(policy(), image_digest="sha256:" + "c" * 64)),
    ]

    for target, snapshot, current_policy in observations:
        assert (
            assess(target, snapshot, passing_checks(), current_policy).fingerprint
            != baseline
        )
