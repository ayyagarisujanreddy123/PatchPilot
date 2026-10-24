"""Real Anthropic streaming SDK exercised entirely over a local HTTP transport."""

import json
from types import SimpleNamespace

import httpx2
import pytest
from anthropic import Anthropic

from patchpilot.webscan import advisor as advisor_module
from patchpilot.webscan.advisor import AnthropicWebsiteAdvisor, WebsiteAdviceError
from patchpilot.webscan.models import HTTPResponse, ScanReport
from patchpilot.webscan.rules import inspect_responses


def observed_report():
    url = "https://example.org/PRIVATE_URL_PATH.php?token=PRIVATE_QUERY_TOKEN"
    report = ScanReport(
        assessment_id="advisor-test", url=url, created_at="2026-10-24T12:00:00Z"
    )
    inspect_responses(
        report,
        (
            HTTPResponse(
                url=url,
                status=200,
                elapsed_ms=12,
                body_truncated=False,
                resolved_ip="93.184.216.34",
                tls_protocol="TLSv1.3",
                headers=(
                    ("Content-Type", "text/html"),
                    ("X-Powered-By", "PHP/5.2.6 PRIVATE_BANNER_SUFFIX"),
                    ("Set-Cookie", "PHPSESSID=PRIVATE_COOKIE_VALUE; Path=/"),
                    ("Authorization", "Bearer PRIVATE_AUTH_VALUE"),
                ),
                body=b'<title>phpinfo()</title><p>PRIVATE_HTML_BODY</p><a href="private.php">Page</a>',
            ),
        ),
    )
    return report


def answer(finding_id="php-version-disclosure"):
    return {
        "summary": "Fresh response observations require owner-reviewed hardening.",
        "recommendations": [
            {
                "findingId": finding_id,
                "explanation": "The observed PHP banner exposes version information.",
                "steps": [
                    "Review the serving PHP configuration",
                    "Stage the change before deployment",
                ],
                "code": "expose_php = Off",
                "verification": "Repeat a normal HTTP request and review response headers.",
            }
        ],
        "furtherChecks": [
            "Inspect the installed runtime with authorized server access."
        ],
    }


def streamed_advisor(
    payload=None, *, text=None, stop_reason="end_turn", status=200, connect_error=False
):
    requests = []
    payload = answer() if payload is None else payload
    text = json.dumps(payload) if text is None else text
    chunks = [text[:20], text[20:60], text[60:]]

    def event(kind, data):
        return f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    def respond(request):
        requests.append(request)
        if connect_error:
            raise httpx2.ConnectError(
                "PRIVATE_PROVIDER_CONNECTION_DETAIL", request=request
            )
        if status != 200:
            return httpx2.Response(
                status,
                json={
                    "error": {
                        "type": "overloaded_error",
                        "message": "PRIVATE_PROVIDER_ERROR_BODY",
                    }
                },
            )
        wire = event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_local_stream",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "test-stream-model",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 111, "output_tokens": 0},
                },
            },
        )
        wire += event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )
        for chunk in chunks:
            wire += event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": chunk},
                },
            )
        wire += event("content_block_stop", {"type": "content_block_stop", "index": 0})
        wire += event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 42},
            },
        )
        wire += event("message_stop", {"type": "message_stop"})
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=wire.encode()
        )

    client = Anthropic(
        api_key="unit-test-only-not-a-credential",
        max_retries=0,
        base_url="https://api.anthropic.com",
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
    )
    return AnthropicWebsiteAdvisor(client, model="test-request-model"), requests


def test_streamed_sdk_progress_and_validated_recommendations_preserve_provenance(
    monkeypatch,
):
    tick = iter([100.0, 101.2, 102.4, 103.6])
    monkeypatch.setattr(
        advisor_module, "time", SimpleNamespace(monotonic=lambda: next(tick))
    )
    advisor, requests = streamed_advisor()
    progress = []
    try:
        analysis = advisor.analyze(observed_report(), progress.append)
    finally:
        advisor.close()
    assert analysis.source == "ANTHROPIC"
    assert analysis.model_id == "test-stream-model"
    assert analysis.provider_message_id == "msg_local_stream"
    assert (analysis.input_tokens, analysis.output_tokens) == (111, 42)
    assert [fix.finding_id for fix in analysis.recommendations] == [
        "php-version-disclosure"
    ]
    assert analysis.recommendations[0].requires_server_access is True
    assert (
        len([message for message in progress if "characters received" in message]) == 3
    )
    assert any("20 characters received" in message for message in progress)
    assert any("60 characters received" in message for message in progress)
    assert "completed 1 validated" in progress[-1]
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["stream"] is True
    assert body["max_tokens"] == 6000
    assert body["output_config"]["effort"] == "medium"
    schema = body["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    identifiers = schema["properties"]["recommendations"]["items"]["properties"][
        "findingId"
    ]["enum"]
    assert set(identifiers) == {
        finding.finding_id for finding in observed_report().findings
    }
    assert requests[0].url.host == "api.anthropic.com"


def test_raw_urls_html_and_cookie_or_authorization_values_do_not_enter_model_input():
    advisor, requests = streamed_advisor()
    report = observed_report()
    try:
        advisor.analyze(report, lambda message: None)
    finally:
        advisor.close()
    body = requests[0].content.decode()
    for secret in (
        report.url,
        "PRIVATE_URL_PATH",
        "PRIVATE_QUERY_TOKEN",
        "PRIVATE_HTML_BODY",
        "PRIVATE_COOKIE_VALUE",
        "PRIVATE_AUTH_VALUE",
        "PRIVATE_BANNER_SUFFIX",
        "unit-test-only-not-a-credential",
    ):
        assert secret not in body
    payload = json.loads(json.loads(requests[0].content)["messages"][0]["content"])
    assert payload["phpDetection"]["version"] == "5.2.6"
    assert "PHPSESSID" in body and "cookie value omitted" in body
    assert all("url" not in item for item in payload["technicalEvidence"])
    assert all(
        set(item) == {"status", "tlsProtocol", "truncated"}
        for item in payload["responseSummary"]
    )


@pytest.mark.parametrize("mutation", ["invented", "duplicate", "empty", "extra"])
def test_invented_or_invalid_fix_contracts_are_rejected(mutation):
    payload = answer()
    if mutation == "invented":
        payload["recommendations"][0]["findingId"] = "INVENTED_SQL_INJECTION"
    elif mutation == "duplicate":
        payload["recommendations"] *= 2
    elif mutation == "empty":
        payload["recommendations"] = []
    else:
        payload["inventedObservations"] = ["PRIVATE_PROVIDER_RESPONSE"]
    advisor, _ = streamed_advisor(payload)
    try:
        with pytest.raises(WebsiteAdviceError, match="evidence-bound") as raised:
            advisor.analyze(observed_report(), lambda message: None)
        assert "PRIVATE_PROVIDER_RESPONSE" not in str(raised.value)
    finally:
        advisor.close()


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal", "tool_use"])
def test_incomplete_or_refused_streams_never_become_analysis(stop_reason):
    advisor, _ = streamed_advisor(stop_reason=stop_reason)
    try:
        with pytest.raises(
            WebsiteAdviceError, match="no AI recommendations were accepted"
        ):
            advisor.analyze(observed_report(), lambda message: None)
    finally:
        advisor.close()


@pytest.mark.parametrize("failure", ["http", "connection"])
def test_provider_failures_are_safe_and_have_no_retry_or_fallback(failure):
    advisor, requests = streamed_advisor(
        status=503 if failure == "http" else 200, connect_error=failure == "connection"
    )
    try:
        with pytest.raises(WebsiteAdviceError) as raised:
            advisor.analyze(observed_report(), lambda message: None)
        assert "PRIVATE_PROVIDER" not in str(raised.value)
        assert "Live observations remain available" in str(raised.value)
        assert len(requests) == 1
    finally:
        advisor.close()


def test_oversized_stream_and_malformed_json_are_rejected():
    for content in ("X" * 30001, '{"summary": "PRIVATE_MALFORMED_RESPONSE"'):
        advisor, _ = streamed_advisor(text=content)
        try:
            with pytest.raises(WebsiteAdviceError) as raised:
                advisor.analyze(observed_report(), lambda message: None)
            assert "PRIVATE_MALFORMED_RESPONSE" not in str(raised.value)
        finally:
            advisor.close()


def test_no_findings_does_not_force_invented_recommendations():
    report = ScanReport(
        assessment_id="no-findings", url="https://example.org/", created_at="now"
    )
    advisor, _ = streamed_advisor(
        {
            "summary": "No rule findings; the public-response scope remains limited.",
            "recommendations": [],
            "furtherChecks": [],
        }
    )
    try:
        result = advisor.analyze(report, lambda message: None)
        assert result.recommendations == []
        assert result.provider_message_id == "msg_local_stream"
    finally:
        advisor.close()
