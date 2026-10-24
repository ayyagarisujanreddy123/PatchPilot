"""Reviewed repair policy; model output can select aliases, never operations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class PolicyError(ValueError):
    """The requested repair is outside the reviewed policy."""


def parse_version(value: object) -> tuple[int, int, int]:
    """Accept upstream stable versions only; vendor backports need their own policy."""
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise PolicyError(
            "Unsupported PHP version; expected an upstream stable release"
        )
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _text(value: object, name: str, limit: int = 64) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PolicyError(f"Invalid {name}")
    return value


def _slug(value: object, name: str) -> str:
    text = _text(value, name)
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", text):
        raise PolicyError(f"Invalid {name}")
    return text


def _digest(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise PolicyError("An immutable approved image digest is required")
    return value


def _bytes(value: object) -> int:
    if not isinstance(value, str):
        raise PolicyError("Invalid PHP size setting")
    match = re.fullmatch(r"([1-9][0-9]*)([KMG]?)", value)
    if match is None:
        raise PolicyError("Invalid PHP size setting")
    multipliers = {"": 1, "K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024}
    return int(match[1]) * multipliers[match[2]]


@dataclass(frozen=True)
class RepairPlan:
    target_image_alias: str
    config_profile_id: str
    rationale: str = "Apply the approved runtime and configuration profile."

    def __post_init__(self) -> None:
        _slug(self.target_image_alias, "target image alias")
        _slug(self.config_profile_id, "configuration profile")
        _text(self.rationale, "rationale", 500)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RepairPlan:
        fields = {"targetImageAlias", "configProfileId", "rationale"}
        if set(value) != fields:
            raise PolicyError("Repair plan fields must match the typed contract")
        return cls(
            _slug(value["targetImageAlias"], "target image alias"),
            _slug(value["configProfileId"], "configuration profile"),
            _text(value["rationale"], "rationale", 500),
        )


@dataclass(frozen=True)
class ConfigurationProfile:
    profile_id: str
    upload_max_filesize: str
    post_max_size: str
    upload_progress_enabled: bool = False

    def __post_init__(self) -> None:
        _slug(self.profile_id, "profile ID")
        if self.upload_progress_enabled is not False:
            raise PolicyError("Upload-progress mitigation must remain enabled")
        if _bytes(self.post_max_size) <= _bytes(self.upload_max_filesize):
            raise PolicyError("POST size must exceed the upload size limit")


@dataclass(frozen=True)
class ValidatedPlan:
    plan: RepairPlan
    image_digest: str
    profile: ConfigurationProfile


@dataclass(frozen=True)
class SecurityPolicy:
    revision: str
    runtime_branch: str
    fixed_version: str
    target_image_alias: str
    image_digest: str | None
    profiles: tuple[ConfigurationProfile, ...]
    registered_site_ids: frozenset[str]
    max_candidate_attempts: int

    def validate_plan(self, site_id: str, plan: RepairPlan) -> ValidatedPlan:
        if site_id not in self.registered_site_ids:
            raise PolicyError("Site is not registered for repair")
        if plan.target_image_alias != self.target_image_alias:
            raise PolicyError("Target image alias is not approved")
        profile = next(
            (
                item
                for item in self.profiles
                if item.profile_id == plan.config_profile_id
            ),
            None,
        )
        if profile is None:
            raise PolicyError("Configuration profile is not approved")
        return ValidatedPlan(plan, _digest(self.image_digest), profile)


def load_policy(
    path: Path,
    *,
    registered_site_ids: frozenset[str],
    approved_image_digest: str | None = None,
) -> SecurityPolicy:
    """The digest override comes from the trusted image registry, never the model."""
    document = json.loads(path.read_text(encoding="utf-8"))
    fields = {
        "schemaVersion",
        "revision",
        "runtimeBranch",
        "fixedVersion",
        "fixedAdvisories",
        "mitigationAdvisory",
        "targetImageAlias",
        "targetImageDigest",
        "maxCandidateAttempts",
        "profiles",
        "sourceUrl",
        "reviewedOn",
    }
    if not isinstance(document, dict) or set(document) != fields:
        raise PolicyError("Policy fields do not match schema version 1")
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise PolicyError("Unsupported policy schema version")
    fixed_version = _text(document["fixedVersion"], "fixed version")
    major, minor, _ = parse_version(fixed_version)
    if document["runtimeBranch"] != f"{major}.{minor}":
        raise PolicyError("Fixed version must belong to the approved runtime branch")
    attempts = document["maxCandidateAttempts"]
    if type(attempts) is not int or attempts not in (1, 2):
        raise PolicyError("Candidate attempts must be one or two")
    configured_digest = document["targetImageDigest"]
    if configured_digest is not None:
        _digest(configured_digest)
    if approved_image_digest is not None:
        _digest(approved_image_digest)
        if configured_digest is not None and configured_digest != approved_image_digest:
            raise PolicyError("Resolved image digest differs from the approved policy")
    raw_profiles = document["profiles"]
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise PolicyError("At least one registered configuration profile is required")
    profiles = []
    for name, settings in raw_profiles.items():
        if not isinstance(settings, dict) or set(settings) != {
            "session.upload_progress.enabled",
            "upload_max_filesize",
            "post_max_size",
        }:
            raise PolicyError("Configuration profile fields are not approved")
        if settings["session.upload_progress.enabled"] != "0":
            raise PolicyError("Upload-progress mitigation must remain enabled")
        profiles.append(
            ConfigurationProfile(
                _slug(name, "profile ID"),
                _text(settings["upload_max_filesize"], "upload size"),
                _text(settings["post_max_size"], "POST size"),
            )
        )
    for site_id in registered_site_ids:
        _slug(site_id, "site ID")
    return SecurityPolicy(
        _text(document["revision"], "policy revision"),
        document["runtimeBranch"],
        fixed_version,
        _slug(document["targetImageAlias"], "target image alias"),
        approved_image_digest
        if approved_image_digest is not None
        else configured_digest,
        tuple(profiles),
        registered_site_ids,
        attempts,
    )
