"""Security policy must reject unregistered or unresolved repair operations."""

import json
from pathlib import Path

import pytest

from patchpilot.core.policy import PolicyError, RepairPlan, load_policy, parse_version

POLICY_FILE = Path(__file__).resolve().parents[2] / "config/advisories.json"
TEST_DIGEST = "sha256:" + "a" * 64
REGISTERED_SITES = frozenset({"pantry-a", "clinic-a"})


def test_checked_in_policy_requires_a_resolved_image_before_execution():
    policy = load_policy(POLICY_FILE, registered_site_ids=REGISTERED_SITES)

    with pytest.raises(PolicyError, match="digest"):
        policy.validate_plan("pantry-a", RepairPlan("php83_patched", "preserve_basic"))


def test_allowed_plan_resolves_only_registered_settings():
    policy = load_policy(
        POLICY_FILE,
        registered_site_ids=REGISTERED_SITES,
        approved_image_digest=TEST_DIGEST,
    )

    plan = policy.validate_plan(
        "clinic-a", RepairPlan("php83_patched", "preserve_uploads", "Preserve uploads")
    )

    assert plan.image_digest == TEST_DIGEST
    assert plan.profile.upload_max_filesize == "8M"
    assert plan.profile.post_max_size == "10M"
    assert plan.profile.upload_progress_enabled is False


@pytest.mark.parametrize(
    ("site_id", "alias", "profile"),
    [
        ("not-registered", "php83_patched", "preserve_basic"),
        ("pantry-a", "attacker/image:latest", "preserve_basic"),
        ("pantry-a", "php83_patched", "arbitrary_profile"),
    ],
)
def test_unapproved_targets_images_and_profiles_are_rejected(site_id, alias, profile):
    policy = load_policy(
        POLICY_FILE,
        registered_site_ids=REGISTERED_SITES,
        approved_image_digest=TEST_DIGEST,
    )

    with pytest.raises(PolicyError):
        policy.validate_plan(site_id, RepairPlan(alias, profile))


@pytest.mark.parametrize(
    "digest", ["php:latest", "sha256:abc", "", "sha256:" + "G" * 64]
)
def test_unpinned_or_malformed_image_identity_is_rejected(digest):
    with pytest.raises(PolicyError, match="digest"):
        load_policy(
            POLICY_FILE,
            registered_site_ids=REGISTERED_SITES,
            approved_image_digest=digest,
        )


@pytest.mark.parametrize(
    "extra", [{"command": "docker run arbitrary"}, {"disableTests": True}]
)
def test_model_output_cannot_add_execution_instructions(extra):
    with pytest.raises(PolicyError, match="fields"):
        RepairPlan.from_mapping(
            {
                "targetImageAlias": "php83_patched",
                "configProfileId": "preserve_basic",
                **extra,
            }
        )


@pytest.mark.parametrize("value", [None, 1, "", "x" * 501])
def test_plan_rationale_has_a_bounded_string_contract(value):
    with pytest.raises(PolicyError):
        RepairPlan.from_mapping(
            {
                "targetImageAlias": "php83_patched",
                "configProfileId": "preserve_basic",
                "rationale": value,
            }
        )


@pytest.mark.parametrize(
    ("setting", "value"),
    [("session.upload_progress.enabled", "1"), ("post_max_size", "1M")],
)
def test_profiles_cannot_remove_mitigation_or_invert_upload_limits(
    tmp_path, setting, value
):
    document = json.loads(POLICY_FILE.read_text())
    document["profiles"]["preserve_uploads"][setting] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))

    with pytest.raises(PolicyError):
        load_policy(path, registered_site_ids=REGISTERED_SITES)


def test_policy_cannot_raise_candidate_attempts_above_two(tmp_path):
    document = json.loads(POLICY_FILE.read_text())
    document["maxCandidateAttempts"] = 20
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))

    with pytest.raises(PolicyError, match="attempts"):
        load_policy(path, registered_site_ids=REGISTERED_SITES)


@pytest.mark.parametrize(
    "version", ["8.3.36-dev", "8.3.36-ubuntu1", "8.3", "8.3.36;id", None]
)
def test_unsupported_version_strings_are_not_guessed(version):
    with pytest.raises(PolicyError, match="version"):
        parse_version(version)


def test_version_comparison_is_numeric():
    assert parse_version("8.3.9") < parse_version("8.3.36")
