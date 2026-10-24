"""The website assessment API and private HTTP transport boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from patchpilot.shared.contracts import ContractModel

ScanState = Literal["QUEUED", "COLLECTING", "ANALYZING", "COMPLETED", "FAILED"]


@dataclass(frozen=True)
class HTTPResponse:
    url: str
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    body_truncated: bool
    elapsed_ms: int
    resolved_ip: str
    tls_protocol: str | None = None
    certificate_expires_at: str | None = None


class Evidence(ContractModel):
    evidence_id: str
    url: str
    kind: str
    label: str
    observed: str
    collected_at: str


class ResponseSummary(ContractModel):
    url: str
    status: int
    elapsed_ms: int
    body_sha256: str
    bytes_read: int
    truncated: bool
    tls_protocol: str | None = None
    header_names: list[str] = Field(default_factory=list)


class PHPDetection(ContractModel):
    status: Literal["REPORTED", "INFERRED", "UNKNOWN"] = "UNKNOWN"
    version: str | None = None
    explanation: str = "PHP could not be confirmed from the collected public responses."
    evidence_ids: list[str] = Field(default_factory=list)


class Finding(ContractModel):
    finding_id: str
    title: str
    severity: Literal["info", "low", "medium", "high"]
    confidence: Literal["OBSERVED", "INFERRED"]
    description: str
    evidence_ids: list[str]
    recommendation: str
    references: list[str] = Field(default_factory=list)


class FixRecommendation(ContractModel):
    finding_id: str
    explanation: str = Field(max_length=1500)
    steps: list[str] = Field(max_length=8)
    code: str = Field(max_length=5000)
    verification: str = Field(max_length=1500)
    requires_server_access: bool = True


class AIAnalysis(ContractModel):
    source: Literal["ANTHROPIC"] = "ANTHROPIC"
    model_id: str
    provider_message_id: str
    input_tokens: int
    output_tokens: int
    summary: str
    recommendations: list[FixRecommendation] = Field(default_factory=list)
    further_checks: list[str] = Field(default_factory=list)


class ScanEvent(ContractModel):
    sequence: int
    timestamp: str
    stage: ScanState
    message: str


class ScanReport(ContractModel):
    assessment_id: str
    url: str
    state: ScanState = "QUEUED"
    created_at: str
    finished_at: str | None = None
    stage_message: str = "Waiting to inspect the public website"
    responses: list[ResponseSummary] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    php_detection: PHPDetection = Field(default_factory=PHPDetection)
    findings: list[Finding] = Field(default_factory=list)
    analysis: AIAnalysis | None = None
    coverage: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    events: list[ScanEvent] = Field(default_factory=list)
    error: str | None = None
