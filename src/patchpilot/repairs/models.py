"""Public connected-repair contracts; credentials and source archives stay private."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, field_validator

from patchpilot.shared.contracts import ContractModel

Capability = Literal["homepage", "contact", "upload"]
RepairState = Literal[
    "QUEUED",
    "FETCHING",
    "BASELINE",
    "PLANNING",
    "STAGING",
    "READY_TO_PUBLISH",
    "NO_CHANGE",
    "REJECTED",
    "PUBLISHING",
    "PUBLISHED",
    "FAILED",
]


class SiteManifest(ContractModel):
    schema_version: Literal[1] = 1
    site_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    document_root: str
    php_ini: str
    capabilities: list[Capability] = Field(min_length=1, max_length=3)
    homepage: Literal["/"] = "/"
    contact: str = "/contact.php"
    upload: str = "/upload.php"

    @field_validator("document_root", "php_ini")
    @classmethod
    def safe_path(cls, value):
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,180}", value) or any(
            part in {"", ".", ".."} for part in value.split("/")
        ):
            raise ValueError("Repository paths must be relative regular-file paths")
        return value

    @field_validator("contact", "upload")
    @classmethod
    def safe_route(cls, value):
        import re

        if (
            not re.fullmatch(r"/[A-Za-z0-9_/-]+\.php", value)
            or ".." in value
            or "//" in value
        ):
            raise ValueError("Checks require a simple PHP route")
        return value

    @field_validator("capabilities")
    @classmethod
    def required_homepage(cls, value):
        if "homepage" not in value or len(value) != len(set(value)):
            raise ValueError("Homepage and unique capabilities are required")
        return value


class GitHubStatus(ContractModel):
    available: bool
    login: str | None = None
    message: str


class RepositoryConnection(ContractModel):
    connection_id: str
    assessment_id: str
    url: str
    repository: str
    repository_url: str
    default_branch: str
    base_commit: str
    site_id: str
    manifest: SiteManifest
    capabilities: list[Capability]
    created_at: str
    identity_explanation: str = "The website's deployment marker matches this repository and commit. This is a declared deployment identity, not independent build attestation."


class VerificationCheck(ContractModel):
    check_id: str
    label: str
    phase: Literal["BASELINE", "CANDIDATE"]
    passed: bool
    expected: str
    observed: str
    duration_ms: int = 0


@dataclass(frozen=True)
class SandboxResult:
    checks: tuple[VerificationCheck, ...]
    runtime: dict[str, str | bool]
    image_digest: str


class ConfigChange(ContractModel):
    key: Literal["display_errors", "display_startup_errors", "log_errors", "expose_php"]
    value: Literal["Off", "On"]


class RepairProposal(ContractModel):
    rationale: str = Field(min_length=1, max_length=1000)
    changes: list[ConfigChange] = Field(min_length=1, max_length=4)
    model_id: str
    provider_message_id: str
    input_tokens: int
    output_tokens: int


class RepositoryPatch(ContractModel):
    path: str
    before_blob_sha: str
    after_sha256: str
    unified_diff: str


class RepairEvent(ContractModel):
    sequence: int
    timestamp: str
    state: RepairState
    message: str


class PullRequest(ContractModel):
    url: str
    number: int
    branch: str
    commit: str
    draft: bool = True


class RepositoryRepairReport(ContractModel):
    repair_id: str
    connection_id: str
    assessment_id: str
    repository: str
    url: str
    base_commit: str
    state: RepairState = "QUEUED"
    created_at: str
    finished_at: str | None = None
    stage_message: str = "Waiting to prepare an isolated repair"
    capabilities: list[Capability]
    checks: list[VerificationCheck] = Field(default_factory=list)
    proposal: RepairProposal | None = None
    patch: RepositoryPatch | None = None
    image_digest: str | None = None
    pull_request: PullRequest | None = None
    events: list[RepairEvent] = Field(default_factory=list)
    error: str | None = None
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Only the supported PHP error-display/logging and version-banner configuration is changed.",
            "Behavior checks run on an isolated reconstruction of the declared repository commit, not on production.",
            "A tested pull request has not been deployed. Merge, deployment, and production verification remain under your control.",
        ]
    )
