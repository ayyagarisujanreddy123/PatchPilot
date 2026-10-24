"""Core value objects; backend schemas adapt these without owning repair rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Site:
    site_id: str
    base_url: str
    template_revision: str
    capabilities: frozenset[str] = frozenset({"homepage", "contact"})

    @property
    def required_checks(self) -> frozenset[str]:
        checks = {
            "runtime_version",
            "sapi",
            "upload_progress",
            "deployment_identity",
            "homepage",
            "contact_valid",
            "contact_invalid",
        }
        if "upload" in self.capabilities:
            checks.update({"upload_size", "upload_hash"})
        return frozenset(checks)


@dataclass(frozen=True)
class DeploymentSnapshot:
    site_id: str
    deployment_id: str
    image_id: str
    application_hash: str
    configuration_hash: str
    php_version: str
    sapi: str
    upload_progress_enabled: bool
    base_image_digest: str | None = None


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    passed: bool
    message: str = ""


def checks_complete(site: Site, checks: tuple[CheckResult, ...]) -> bool:
    identifiers = [check.check_id for check in checks]
    return (
        len(identifiers) == len(set(identifiers))
        and site.required_checks <= set(identifiers)
        and all(check.passed is True for check in checks)
    )
