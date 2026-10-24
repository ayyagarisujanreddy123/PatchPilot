"""Findings derived only from fresh, public HTTP observations.

Missing headers are hardening gaps, never proof of an exploitable application
bug. A banner reports a version; it cannot establish installed patch/backports.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from patchpilot.webscan.models import (
    Evidence,
    Finding,
    HTTPResponse,
    PHPDetection,
    ResponseSummary,
    ScanReport,
)

PHP_SUPPORT = "https://www.php.net/supported-versions.php"
PHP_HIDE = "https://www.php.net/manual/en/ini.core.php#ini.expose-php"
PHP_SESSION = "https://www.php.net/manual/en/session.security.ini.php"
PHP_ERRORS = (
    "https://www.php.net/manual/en/errorfunc.configuration.php#ini.display-errors"
)
HEADERS = "https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html"
VERSION = re.compile(
    r"\bPHP/([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[A-Za-z0-9.]+)?)", re.IGNORECASE
)


class _Signals(HTMLParser):
    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.php_link = False
        self.page = urlsplit(page_url)

    def handle_starttag(self, tag, attrs):
        if tag not in {"a", "form"}:
            return
        for name, value in attrs:
            if name in {"href", "action"} and value:
                try:
                    target = urlsplit(urljoin(self.page.geturl(), value))
                    same_origin = (
                        target.scheme,
                        target.hostname,
                        target.port or (443 if target.scheme == "https" else 80),
                    ) == (
                        self.page.scheme,
                        self.page.hostname,
                        self.page.port or (443 if self.page.scheme == "https" else 80),
                    )
                    self.php_link |= same_origin and target.path.lower().endswith(
                        ".php"
                    )
                except ValueError:
                    continue


def _framing_restriction(policies):
    def valid_source(source):
        if source == "'self'":
            return True
        if not re.fullmatch(r"https?://(?:\*\.)?[a-z0-9.-]+(?::[0-9]+)?/?", source):
            return False
        try:
            parsed = urlsplit(source.replace("://*.", "://"))
            return bool(
                parsed.hostname
                and len(parsed.hostname) <= 253
                and all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in parsed.hostname.split(".")
                )
                and (parsed.port is None or 1 <= parsed.port <= 65535)
            )
        except ValueError:
            return False

    for policy in policies:
        for directive in policy.split(";"):
            tokens = directive.lower().split()
            if not tokens or tokens[0] != "frame-ancestors":
                continue
            sources = tokens[1:]
            if sources == ["'none'"]:
                return True
            if sources and all(valid_source(token) for token in sources):
                return True
            # Browsers use only the first occurrence of a directive per policy.
            break
    return False


def inspect_responses(report: ScanReport, responses: tuple[HTTPResponse, ...]) -> None:
    """Populate a report without retaining HTML, cookie values, or secret headers."""
    now = datetime.now(UTC).isoformat()
    report.coverage = [
        "Fresh normal HTTP GET requests to the submitted page and validated redirects",
        "Public PHP signals, transport, security headers, and session-cookie attributes",
    ]
    report.limitations = [
        "This is a public-response assessment, not a complete penetration test or a safe-site certification.",
        "SQL injection, authentication logic, filesystem permissions, and server-side source were not tested.",
        "A version banner may be hidden, inaccurate, or include vendor backports; verify the installed runtime before upgrading.",
        "No server changes were made. Suggested fixes require owner review and authorized server/source access.",
    ]
    report.responses = []
    report.evidence = []
    report.findings = []
    report.php_detection = PHPDetection()
    if not responses:
        raise ValueError("No public HTTP response was collected")

    def evidence(response, kind, label, observed):
        item = Evidence(
            evidence_id=f"evidence-{len(report.evidence) + 1}",
            url=response.url,
            kind=kind,
            label=label,
            observed=observed[:400],
            collected_at=now,
        )
        report.evidence.append(item)
        return item.evidence_id

    def finding(
        key,
        title,
        severity,
        description,
        ids,
        recommendation,
        references,
        confidence="OBSERVED",
    ):
        if any(item.finding_id == key for item in report.findings):
            return
        report.findings.append(
            Finding(
                finding_id=key,
                title=title,
                severity=severity,
                confidence=confidence,
                description=description,
                evidence_ids=ids,
                recommendation=recommendation,
                references=references,
            )
        )

    for response in responses:
        report.responses.append(
            ResponseSummary(
                url=response.url,
                status=response.status,
                elapsed_ms=response.elapsed_ms,
                body_sha256=hashlib.sha256(response.body).hexdigest(),
                bytes_read=len(response.body),
                truncated=response.body_truncated,
                tls_protocol=response.tls_protocol,
                header_names=sorted({key.lower() for key, _ in response.headers}),
            )
        )
        evidence(
            response,
            "http",
            "HTTP response",
            f"HTTP {response.status}; {len(response.body)} bytes collected; SHA-256 {hashlib.sha256(response.body).hexdigest()}",
        )
        headers = {}
        for key, value in response.headers:
            headers.setdefault(key.lower(), []).append(value)
        version_match = VERSION.search(
            " ".join(headers.get("x-powered-by", []) + headers.get("server", []))
        )
        if version_match:
            version = version_match[1]
            identifier = evidence(
                response,
                "php",
                "Reported PHP version",
                f"Public response banner reports PHP/{version}; runtime not independently inspected",
            )
            report.php_detection = PHPDetection(
                status="REPORTED",
                version=version,
                explanation="PHP is reported by an HTTP server header. This is a remote signal, not proof of the installed build.",
                evidence_ids=[identifier],
            )
            finding(
                "php-version-disclosure",
                "PHP version is publicly disclosed",
                "low",
                "The response reveals a PHP release. Hiding it reduces information exposure but does not patch the runtime.",
                [identifier],
                "Review expose_php=Off and web-server banner settings, then verify the response. Keep the actual PHP runtime patched.",
                [PHP_HIDE],
            )
            branch = re.match(r"([0-9]+)\.([0-9]+)", version)
            major, minor = map(int, branch.groups())
            if (major, minor) < (8, 2):
                finding(
                    "php-unsupported-branch",
                    "Reported PHP branch is out of upstream security support",
                    "high",
                    "The reported release predates the branches supported by PHP as reviewed on 2026-10-24. A banner alone does not prove the actual patch or vendor-support status.",
                    [identifier],
                    "Confirm the serving PHP build and any vendor support, plan migration to a currently supported release, stage compatibility tests, and verify the running web process after deployment.",
                    [PHP_SUPPORT],
                    "INFERRED",
                )
        encoding = ",".join(headers.get("content-encoding", [])).lower().strip()
        body = (
            response.body.decode("utf-8", errors="replace")
            if encoding in {"", "identity"}
            else ""
        )
        if encoding not in {"", "identity"}:
            report.limitations.append(
                "A response used an unsupported content encoding; its HTML signals were not evaluated."
            )
        signals = _Signals(response.url)
        try:
            signals.feed(body)
        except (ValueError, AssertionError):
            report.limitations.append(
                "Malformed HTML prevented complete navigation-signal parsing; HTTP evidence remains available."
            )
        if report.php_detection.status == "UNKNOWN" and (
            signals.php_link or urlsplit(response.url).path.lower().endswith(".php")
        ):
            identifier = evidence(
                response,
                "php",
                "PHP-style URL signal",
                "A .php page path or navigation/form target was observed; implementation and PHP version remain unconfirmed",
            )
            report.php_detection = PHPDetection(
                status="INFERRED",
                explanation="PHP-style URLs were observed. They can be rewritten or static, so PHP runtime/version is not confirmed.",
                evidence_ids=[identifier],
            )
        if re.search(r"<title[^>]*>\s*phpinfo\(\)", body, re.IGNORECASE):
            identifier = evidence(
                response,
                "php",
                "PHP diagnostic page",
                "The submitted response has a phpinfo() diagnostic-page title; environment values were omitted",
            )
            finding(
                "php-diagnostic-page",
                "A PHP diagnostic page is publicly visible",
                "medium",
                "A phpinfo-style response can expose runtime and environment details. No environment values are retained by this assessment.",
                [identifier],
                "Remove public phpinfo() output or restrict the diagnostic route to authorized administrators.",
                [PHP_HIDE],
            )
        if re.search(
            r"<(?:b|strong)>\s*(?:Fatal error|Warning|Parse error)\s*:?.{0,120}</(?:b|strong)>[\s\S]{0,700}\bon line\b",
            body,
            re.IGNORECASE,
        ):
            identifier = evidence(
                response,
                "php",
                "PHP-style diagnostic output",
                "A PHP-style error/warning and line marker appear in the public response; raw messages and paths were omitted",
            )
            finding(
                "php-error-disclosure",
                "PHP-style diagnostic output is exposed",
                "medium",
                "The page displays PHP-style error details. Confirm whether this is application output or an intentional example before changing configuration.",
                [identifier],
                "For production, disable display_errors/display_startup_errors and send errors to a protected server log. Fix the underlying error and retest.",
                [PHP_ERRORS],
            )

    final = responses[-1]
    headers = {}
    for key, value in final.headers:
        headers.setdefault(key.lower(), []).append(value)
    https = urlsplit(final.url).scheme == "https"
    identifier = evidence(
        final,
        "transport",
        "Observed transport",
        f"Final page used {'HTTPS with verified TLS' if https else 'unencrypted HTTP'}"
        + (f" ({final.tls_protocol})" if final.tls_protocol else ""),
    )
    if not https:
        finding(
            "unencrypted-http",
            "The assessed page is served over unencrypted HTTP",
            "medium",
            "The final response used HTTP. This observation does not establish whether a separate HTTPS endpoint exists.",
            [identifier],
            "Configure a valid TLS certificate and HTTPS endpoint, redirect HTTP to HTTPS, and test the application before enabling HSTS.",
            [HEADERS],
        )
    html = any(
        "text/html" in value.lower() or "application/xhtml+xml" in value.lower()
        for value in headers.get("content-type", [])
    )
    if html and 200 <= final.status < 300:
        for key, title, recommendation in [
            (
                "content-security-policy",
                "No enforced Content Security Policy was returned",
                "Build and test a site-specific Content-Security-Policy; use report-only during rollout. A missing CSP is not proof of XSS.",
            ),
            (
                "x-content-type-options",
                "Content-type sniffing protection was not observed",
                "Return X-Content-Type-Options: nosniff with correct Content-Type values and retest.",
            ),
        ]:
            values = headers.get(key, [])
            present = any(value.strip() for value in values) and (
                key != "x-content-type-options"
                or any(value.strip().lower() == "nosniff" for value in values)
            )
            identifier = evidence(
                final,
                "header",
                key,
                "Expected response policy observed"
                if present
                else "Expected response policy absent on this HTML response",
            )
            if not present:
                finding(
                    key,
                    title,
                    "low",
                    "This is a response-hardening observation for the assessed page, not a confirmed application exploit.",
                    [identifier],
                    recommendation,
                    [HEADERS],
                )
        framed = _framing_restriction(
            headers.get("content-security-policy", [])
        ) or any(
            value.strip().upper() in {"DENY", "SAMEORIGIN"}
            for value in headers.get("x-frame-options", [])
        )
        identifier = evidence(
            final,
            "header",
            "Framing policy",
            "An enforced framing restriction was observed"
            if framed
            else "No frame-ancestors or supported X-Frame-Options restriction was observed",
        )
        if not framed:
            finding(
                "framing-policy",
                "No framing restriction was observed",
                "low",
                "The response did not expose a supported framing restriction. Whether framing is unwanted depends on the application.",
                [identifier],
                "If embedding is not required, test CSP frame-ancestors 'none' or a deliberate trusted-origin list, with an appropriate X-Frame-Options fallback.",
                [HEADERS],
            )
    if https:
        hsts = ";".join(headers.get("strict-transport-security", []))
        match = re.search(r"(?:^|;)\s*max-age\s*=\s*([0-9]+)", hsts, re.IGNORECASE)
        valid = match is not None and int(match[1]) > 0
        identifier = evidence(
            final,
            "header",
            "HTTPS transport policy",
            "A positive HSTS max-age was observed"
            if valid
            else "No positive HSTS max-age was observed on this HTTPS response",
        )
        if not valid:
            finding(
                "hsts-policy",
                "An HSTS policy was not observed",
                "low",
                "The HTTPS response did not supply a positive HSTS max-age. This does not prove the site is exploitable.",
                [identifier],
                "After confirming HTTPS works across the intended hostnames, deploy and test a suitable HSTS policy. Review subdomains before adding includeSubDomains/preload.",
                [HEADERS],
            )
    for cookie in headers.get("set-cookie", []):
        name = cookie.split("=", 1)[0].strip()
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
            or name.upper() != "PHPSESSID"
        ):
            continue
        attributes = {
            part.split("=", 1)[0].strip().lower() for part in cookie.split(";")[1:]
        }
        missing = [
            flag
            for flag in ("secure", "httponly", "samesite")
            if flag not in attributes
        ]
        identifier = evidence(
            final,
            "cookie",
            "PHP session-cookie attributes",
            "PHPSESSID; "
            + (
                "missing " + ", ".join(missing)
                if missing
                else "Secure, HttpOnly and SameSite attributes observed"
            )
            + "; cookie value omitted",
        )
        if missing:
            finding(
                "php-session-cookie",
                "PHP session-cookie hardening is incomplete",
                "medium",
                "The observed PHPSESSID Set-Cookie header omitted one or more protective attributes. Other routes and authentication flows were not tested.",
                [identifier],
                "Review session.cookie_secure, session.cookie_httponly and session.cookie_samesite for HTTPS/session behavior; validate login and cross-site flows before rollout.",
                [PHP_SESSION],
            )
    if report.php_detection.status == "UNKNOWN":
        report.limitations.append(
            "PHP was not detectable from these responses; this does not prove the site does not use PHP."
        )
    if any(response.body_truncated for response in responses):
        report.limitations.append(
            "A response body reached the size limit; body-based coverage is incomplete."
        )
    if final.status >= 400:
        report.limitations.append(
            f"The final response was HTTP {final.status}; application behavior behind that response was not inspected."
        )
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    report.findings.sort(key=lambda item: order[item.severity])
