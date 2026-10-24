"""Fresh collection, copied progress, and advisor results with no external I/O."""

import hashlib

import pytest

from patchpilot.webscan.advisor import WebsiteAdviceError
from patchpilot.webscan.agent import WebsiteAssessmentAgent
from patchpilot.webscan.models import AIAnalysis, FixRecommendation, HTTPResponse
from patchpilot.webscan.network import PublicHTTPError


def response(version="5.2.6", body=b"<html>PRIVATE_BODY_VALUE</html>"):
    return HTTPResponse(
        url="https://example.org/",
        status=200,
        headers=(
            ("Content-Type", "text/html"),
            ("X-Powered-By", f"PHP/{version}"),
            ("Set-Cookie", "PHPSESSID=PRIVATE_COOKIE_VALUE; Path=/"),
        ),
        body=body,
        body_truncated=False,
        elapsed_ms=23,
        resolved_ip="93.184.216.34",
        tls_protocol="TLSv1.3",
    )


class Transport:
    def __init__(self, *batches, failure=None):
        self.batches = list(batches)
        self.failure = failure
        self.calls = []

    def fetch(self, url, *, timeout_s, max_redirects):
        self.calls.append((url, timeout_s, max_redirects))
        if self.failure:
            raise self.failure
        return self.batches.pop(0)


class Advisor:
    def __init__(self, failure=None):
        self.failure = failure
        self.closed = False
        self.output = None
        self.input = None

    def analyze(self, report, progress):
        self.input = report.model_copy(deep=True)
        progress("Provider stream has started")
        progress("Provider stream received 200 characters")
        if self.failure:
            raise self.failure
        selected = report.findings[0].finding_id
        self.output = AIAnalysis(
            model_id="unit-test-model",
            provider_message_id="msg_unit_test",
            input_tokens=51,
            output_tokens=29,
            summary=f"Advisor output for observed PHP {report.php_detection.version}",
            recommendations=[
                FixRecommendation(
                    finding_id=selected,
                    explanation="Review the observed finding with an authorized owner.",
                    steps=["Confirm the runtime", "Stage and verify the change"],
                    code="; Suggested configuration for owner review only",
                    verification="Repeat the observed HTTP checks after an authorized change.",
                )
            ],
            further_checks=["Authorized source review was not performed."],
        )
        return self.output

    def close(self):
        self.closed = True


def test_fresh_responses_and_actual_advisor_output_drive_completed_report(tmp_path):
    observed = response()
    transport, advisor = Transport((observed,)), Advisor()
    snapshots = []
    agent = WebsiteAssessmentAgent(
        tmp_path, client=transport, advisor_factory=lambda: advisor
    )
    result = agent.run(
        "https://example.org", assessment_id="scan-fresh", emit=snapshots.append
    )

    assert transport.calls == [("https://example.org/", 30, 3)]
    assert result.state == "COMPLETED"
    assert result.finished_at and result.error is None
    assert result.responses[0].body_sha256 == hashlib.sha256(observed.body).hexdigest()
    assert result.responses[0].bytes_read == len(observed.body)
    assert result.php_detection.status == "REPORTED"
    assert result.php_detection.version == "5.2.6"
    assert result.analysis == advisor.output
    assert result.analysis.summary == "Advisor output for observed PHP 5.2.6"
    assert result.analysis.provider_message_id == "msg_unit_test"
    assert result.analysis.recommendations[0].finding_id in {
        finding.finding_id for finding in result.findings
    }
    assert advisor.closed
    assert [snapshot.state for snapshot in snapshots] == [
        "COLLECTING",
        "COLLECTING",
        "ANALYZING",
        "ANALYZING",
        "ANALYZING",
        "COMPLETED",
    ]
    assert any(
        snapshot.stage_message == "Provider stream received 200 characters"
        for snapshot in snapshots
    )
    assert [event.sequence for event in result.events] == list(
        range(1, len(result.events) + 1)
    )
    assert [event.stage for event in result.events] == [
        snapshot.state for snapshot in snapshots
    ]
    assert all(snapshot.analysis is None for snapshot in snapshots[:-1])
    assert "PRIVATE_BODY_VALUE" not in result.model_dump_json()
    assert "PRIVATE_COOKIE_VALUE" not in result.model_dump_json()


def test_emitted_snapshots_and_nested_evidence_are_deep_copies(tmp_path):
    transport, advisor = Transport((response(),)), Advisor()
    snapshots = []
    result = WebsiteAssessmentAgent(
        tmp_path, client=transport, advisor_factory=lambda: advisor
    ).run("https://example.org/", assessment_id="scan-copies", emit=snapshots.append)

    assert len({id(snapshot) for snapshot in snapshots}) == len(snapshots)
    assert snapshots[0].responses == []
    assert snapshots[0].evidence == []
    assert snapshots[0].findings == []
    assert len(snapshots[0].events) == 1
    assert snapshots[1].state == "COLLECTING"
    assert snapshots[1].analysis is None
    before = snapshots[1].model_dump_json()
    result.evidence[0].observed = "Later mutation"
    result.findings[0].evidence_ids.clear()
    result.analysis.recommendations[0].steps.append("Later instruction")
    result.events.clear()
    assert snapshots[1].model_dump_json() == before
    assert snapshots[-1].evidence[0].observed != "Later mutation"
    assert "Later instruction" not in snapshots[-1].analysis.recommendations[0].steps
    assert snapshots[-1].events


@pytest.mark.parametrize(
    "failure",
    [
        WebsiteAdviceError("Safe provider unavailability"),
        RuntimeError("PRIVATE_PROVIDER_DIAGNOSTIC"),
    ],
)
def test_ai_failure_preserves_collected_evidence_and_never_invents_analysis(
    tmp_path, failure
):
    observed = response()
    transport, advisor = Transport((observed,)), Advisor(failure=failure)
    snapshots = []
    result = WebsiteAssessmentAgent(
        tmp_path, client=transport, advisor_factory=lambda: advisor
    ).run(
        "https://example.org/",
        assessment_id="scan-provider-failure",
        emit=snapshots.append,
    )

    assert result.state == "FAILED"
    assert result.finished_at
    assert result.analysis is None
    assert result.php_detection.version == "5.2.6"
    assert result.responses[0].body_sha256 == hashlib.sha256(observed.body).hexdigest()
    assert (
        result.evidence and result.findings and result.coverage and result.limitations
    )
    assert result.events[-1].stage == "FAILED"
    assert snapshots[-1].state == "FAILED"
    assert snapshots[1].state == "COLLECTING" and snapshots[1].responses
    assert all(snapshot.analysis is None for snapshot in snapshots)
    assert "PRIVATE_PROVIDER_DIAGNOSTIC" not in result.model_dump_json()
    assert advisor.closed


def test_missing_provider_configuration_is_checked_after_fresh_collection(tmp_path):
    transport = Transport((response(),))
    advisor_calls = []

    def missing_configuration():
        advisor_calls.append(True)
        raise WebsiteAdviceError(
            "Configure the provider to generate AI recommendations"
        )

    result = WebsiteAssessmentAgent(
        tmp_path, client=transport, advisor_factory=missing_configuration
    ).run(
        "https://example.org/",
        assessment_id="scan-unconfigured",
        emit=lambda snapshot: None,
    )
    assert len(transport.calls) == len(advisor_calls) == 1
    assert result.state == "FAILED"
    assert result.analysis is None
    assert result.responses and result.evidence
    assert result.php_detection.version == "5.2.6"
    assert "Configure the provider" in result.error


def test_collection_failure_does_not_call_the_advisor_or_use_fixture_results(tmp_path):
    transport = Transport(
        failure=PublicHTTPError("Public destination validation failed")
    )
    advisor_calls = []

    def advisor_factory():
        advisor_calls.append(True)
        return Advisor()

    snapshots = []
    result = WebsiteAssessmentAgent(
        tmp_path, client=transport, advisor_factory=advisor_factory
    ).run(
        "https://example.org/", assessment_id="scan-no-response", emit=snapshots.append
    )
    assert result.state == "FAILED"
    assert result.analysis is None
    assert result.responses == result.evidence == result.findings == []
    assert result.php_detection.status == "UNKNOWN"
    assert advisor_calls == []
    assert [snapshot.state for snapshot in snapshots] == ["COLLECTING", "FAILED"]


def test_repeated_assessments_collect_changed_responses_instead_of_reusing_a_report(
    tmp_path,
):
    older, newer = response(), response("8.4.27", b"A changed public page")
    transport = Transport((older,), (newer,))
    advisors = []

    def advisor_factory():
        advisor = Advisor()
        advisors.append(advisor)
        return advisor

    agent = WebsiteAssessmentAgent(
        tmp_path, client=transport, advisor_factory=advisor_factory
    )
    first = agent.run(
        "https://example.org/", assessment_id="scan-first", emit=lambda snapshot: None
    )
    second = agent.run(
        "https://example.org/", assessment_id="scan-second", emit=lambda snapshot: None
    )
    assert first.state == second.state == "COMPLETED"
    assert len(transport.calls) == len(advisors) == 2
    assert first.php_detection.version == "5.2.6"
    assert second.php_detection.version == "8.4.27"
    assert first.responses[0].body_sha256 != second.responses[0].body_sha256
    assert "php-unsupported-branch" in {
        finding.finding_id for finding in first.findings
    }
    assert "php-unsupported-branch" not in {
        finding.finding_id for finding in second.findings
    }
    assert first.analysis.summary != second.analysis.summary
    assert first.assessment_id != second.assessment_id
    assert all(advisor.closed for advisor in advisors)
