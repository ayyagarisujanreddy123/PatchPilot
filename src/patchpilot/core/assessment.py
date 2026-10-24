"""Match observed deployments to the reviewed upstream PHP policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from patchpilot.core.domain import (
    CheckResult,
    DeploymentSnapshot,
    Site,
    checks_complete,
)
from patchpilot.core.policy import PolicyError, SecurityPolicy, parse_version


class Applicability(StrEnum):
    AFFECTED = "AFFECTED"
    NOT_AFFECTED = "NOT_AFFECTED"
    UNSUPPORTED = "UNSUPPORTED"
    BASELINE_FAILED = "BASELINE_FAILED"


@dataclass(frozen=True)
class Assessment:
    applicability: Applicability
    can_repair: bool
    runtime_update_needed: bool
    mitigation_needed: bool
    fingerprint: str
    blocked_reason: str | None = None


def assess(
    site: Site,
    snapshot: DeploymentSnapshot,
    checks: tuple[CheckResult, ...],
    policy: SecurityPolicy,
) -> Assessment:
    fingerprint = _fingerprint(site, snapshot, checks, policy)

    def blocked(state: Applicability, reason: str) -> Assessment:
        return Assessment(state, False, False, False, fingerprint, reason)

    if (
        site.site_id not in policy.registered_site_ids
        or snapshot.site_id != site.site_id
    ):
        return blocked(
            Applicability.UNSUPPORTED, "Deployment does not match a registered site"
        )
    if not {"homepage", "contact"} <= site.capabilities or not site.capabilities <= {
        "homepage",
        "contact",
        "upload",
    }:
        return blocked(
            Applicability.UNSUPPORTED, "Unsupported application capabilities"
        )
    if (
        snapshot.sapi != "apache2handler"
        or type(snapshot.upload_progress_enabled) is not bool
    ):
        return blocked(
            Applicability.UNSUPPORTED, "Unsupported serving runtime observation"
        )
    try:
        current = parse_version(snapshot.php_version)
        fixed = parse_version(policy.fixed_version)
    except PolicyError as error:
        return blocked(Applicability.UNSUPPORTED, str(error))
    if current[:2] != fixed[:2]:
        return blocked(
            Applicability.UNSUPPORTED, "Runtime branch requires a separate policy"
        )
    if not checks_complete(site, checks):
        return blocked(
            Applicability.BASELINE_FAILED, "Baseline checks failed or are incomplete"
        )
    update_needed = current < fixed
    mitigation_needed = snapshot.upload_progress_enabled
    if current > fixed and mitigation_needed:
        return blocked(
            Applicability.UNSUPPORTED,
            "A newer runtime requires a matching approved image",
        )
    if not update_needed and not mitigation_needed:
        return Assessment(Applicability.NOT_AFFECTED, False, False, False, fingerprint)
    reason = None if policy.image_digest else "An approved image digest is required"
    return Assessment(
        Applicability.AFFECTED,
        reason is None,
        update_needed,
        mitigation_needed,
        fingerprint,
        reason,
    )


def _fingerprint(
    site: Site,
    snapshot: DeploymentSnapshot,
    checks: tuple[CheckResult, ...],
    policy: SecurityPolicy,
) -> str:
    data = {
        "site": {
            "id": site.site_id,
            "baseUrl": site.base_url,
            "template": site.template_revision,
            "verifierRevision": site.verifier_revision,
            "capabilities": sorted(site.capabilities),
        },
        "snapshot": asdict(snapshot),
        "checks": sorted((check.check_id, check.passed) for check in checks),
        "policy": {
            "revision": policy.revision,
            "fixedVersion": policy.fixed_version,
            "imageAlias": policy.target_image_alias,
            "imageDigest": policy.image_digest,
            "profiles": [asdict(profile) for profile in policy.profiles],
            "attempts": policy.max_candidate_attempts,
        },
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
