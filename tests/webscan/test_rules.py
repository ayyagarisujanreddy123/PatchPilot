from patchpilot.webscan.models import HTTPResponse, ScanReport
from patchpilot.webscan.rules import inspect_responses


def report(headers=(), body=b"", url="https://example.org/"):
    result = ScanReport(
        assessment_id="scan-test", url=url, created_at="2026-10-24T00:00:00Z"
    )
    inspect_responses(
        result,
        (
            HTTPResponse(
                url, 200, tuple(headers), body, False, 15, "93.184.216.34", "TLSv1.3"
            ),
        ),
    )
    return result


def test_real_response_facts_drive_php_findings_and_redact_cookies():
    result = report(
        [
            ("X-Powered-By", "PHP/5.2.6"),
            ("Content-Type", "text/html"),
            ("Set-Cookie", "PHPSESSID=SECRET_SESSION_VALUE; Path=/"),
        ],
        b'<a href="about.php">About</a>',
        "http://example.org/",
    )
    assert result.php_detection.status == "REPORTED"
    assert result.php_detection.version == "5.2.6"
    assert {
        "php-unsupported-branch",
        "php-version-disclosure",
        "php-session-cookie",
        "unencrypted-http",
    } <= {f.finding_id for f in result.findings}
    assert "SECRET_SESSION_VALUE" not in result.model_dump_json()
    ids = {item.evidence_id for item in result.evidence}
    assert all(set(item.evidence_ids) <= ids for item in result.findings)
    assert (
        next(
            f for f in result.findings if f.finding_id == "php-unsupported-branch"
        ).confidence
        == "INFERRED"
    )


def test_changed_headers_produce_different_facts_not_a_canned_php_result():
    old = report([("X-Powered-By", "PHP/5.2.6")])
    current = report([("X-Powered-By", "PHP/8.4.27")])
    assert old.php_detection.version != current.php_detection.version
    assert "php-unsupported-branch" not in {f.finding_id for f in current.findings}
    assert old.responses[0].body_sha256 == current.responses[0].body_sha256


def test_vendor_suffix_does_not_break_php_branch_comparison():
    result = report([("Server", "Apache PHP/8.3-apache")])
    assert result.php_detection.version == "8.3-apache"
    assert "php-unsupported-branch" not in {f.finding_id for f in result.findings}


def test_absent_php_is_unknown_and_php_paths_are_only_inference():
    assert (
        report(body=b"A website about PHP development").php_detection.status
        == "UNKNOWN"
    )
    inferred = report(body=b'<a href="index.php">Home</a>')
    assert inferred.php_detection.status == "INFERRED"
    assert inferred.php_detection.version is None
    assert (
        report(
            body=b'<a href="https://external.example/index.php">PHP</a>'
        ).php_detection.status
        == "UNKNOWN"
    )


def test_empty_csp_and_unrestricted_framing_do_not_claim_protection():
    for csp in (
        "",
        "frame-ancestors *",
        "frame-ancestors",
        "frame-ancestors garbage",
        "frame-ancestors *; frame-ancestors 'none'",
        "frame-ancestors https://...",
        "frame-ancestors https://example.org:99999",
    ):
        result = report(
            [("Content-Type", "text/html"), ("Content-Security-Policy", csp)]
        )
        assert "framing-policy" in {f.finding_id for f in result.findings}
        if not csp:
            assert "content-security-policy" in {f.finding_id for f in result.findings}


def test_header_gaps_are_not_exploit_confirmations_and_policy_can_pass():
    result = report(
        [
            ("Content-Type", "text/html"),
            ("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"),
            ("X-Content-Type-Options", "nosniff"),
            ("Strict-Transport-Security", "max-age=31536000"),
        ]
    )
    assert result.findings == []
    assert result.php_detection.status == "UNKNOWN"
    assert any("SQL injection" in item for item in result.limitations)


def test_php_error_output_is_not_retained_in_evidence():
    result = report(
        body=b"<b>Fatal error</b>: unknown function in <b>/private/SECRET_PATH.php</b> on line <b>4</b>"
    )
    assert any(f.finding_id == "php-error-disclosure" for f in result.findings)
    assert "SECRET_PATH" not in result.model_dump_json()
