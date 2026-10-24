"""One real website -> fresh evidence -> streamed Anthropic fix recommendations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from patchpilot.webscan.advisor import AnthropicWebsiteAdvisor, WebsiteAdviceError
from patchpilot.webscan.models import ScanEvent, ScanReport
from patchpilot.webscan.network import (
    PublicHTTPClient,
    PublicHTTPError,
    validate_public_url,
)
from patchpilot.webscan.rules import inspect_responses


def _now():
    return datetime.now(UTC).isoformat()


class WebsiteAssessmentAgent:
    def __init__(self, workspace_root=None, *, client=None, advisor_factory=None):
        self.root = Path(workspace_root or Path(__file__).resolve().parents[3])
        self.client = client or PublicHTTPClient()
        self.advisor_factory = advisor_factory or (
            lambda: AnthropicWebsiteAdvisor.from_environment(self.root)
        )

    def run(
        self, url: str, *, assessment_id: str, emit: Callable[[ScanReport], None]
    ) -> ScanReport:
        report = ScanReport(
            assessment_id=assessment_id, url=validate_public_url(url), created_at=_now()
        )

        def publish(state, message):
            report.state, report.stage_message = state, message
            report.events.append(
                ScanEvent(
                    sequence=len(report.events) + 1,
                    timestamp=_now(),
                    stage=state,
                    message=message,
                )
            )
            emit(report.model_copy(deep=True))

        try:
            publish(
                "COLLECTING",
                "Resolving and validating the public destination, then requesting its current page",
            )
            responses = self.client.fetch(report.url, timeout_s=30, max_redirects=3)
            inspect_responses(report, responses)
            publish(
                "COLLECTING",
                f"Collected {len(responses)} real HTTP response(s); assessed PHP signals, transport, headers and session attributes",
            )
            publish(
                "ANALYZING",
                "Victor is reviewing the freshly collected website evidence",
            )
            advisor = self.advisor_factory()
            try:
                report.analysis = advisor.analyze(
                    report, lambda message: publish("ANALYZING", message)
                )
            finally:
                advisor.close()
            report.finished_at = _now()
            publish(
                "COMPLETED",
                "Victor’s assessment and fix recommendations are ready. No server changes were made.",
            )
        except (PublicHTTPError, WebsiteAdviceError) as error:
            report.error, report.finished_at = str(error), _now()
            publish("FAILED", report.error)
        except (ValueError, OSError, RuntimeError, TypeError):
            report.error = "The assessment could not finish. Review any collected evidence and retry; no result was fabricated."
            report.finished_at = _now()
            publish("FAILED", report.error)
        return report
