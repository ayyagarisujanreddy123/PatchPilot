"""HTTP Verifier for PatchPilot sites.

Executes baseline, candidate, live, and restoration checks.
Verifies runtime probe, organization homepage, contact form,
and optional 3 MiB multipart upload with byte-count and SHA-256 assertions.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CheckResult:
    """Outcome of a single verification assertion."""
    check_id: str
    name: str
    phase: str  # BASELINE, CANDIDATE, LIVE, RESTORATION
    passed: bool
    expected: Any
    observed: Any
    duration_ms: float
    error_message: Optional[str] = None


class SiteVerifier:
    """Runs phase-specific HTTP checks against a deployed site or candidate."""

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout = timeout_seconds

    def check(
        self,
        site: Dict[str, Any],
        endpoint: str,
        phase: str,  # BASELINE, CANDIDATE, LIVE, RESTORATION
        expected_deployment_id: Optional[str] = None,
        expected_php_version_prefix: Optional[str] = None,
        expected_mitigation: Optional[bool] = None
    ) -> List[CheckResult]:
        """Run all applicable checks for the given site and phase."""
        results: List[CheckResult] = []

        # 1. Serving Runtime Probe Check
        results.append(self._check_runtime(
            endpoint=endpoint,
            phase=phase,
            expected_deployment_id=expected_deployment_id,
            expected_php_prefix=expected_php_version_prefix,
            expected_mitigation=expected_mitigation
        ))

        # 2. Homepage Content Check
        results.append(self._check_homepage(
            endpoint=endpoint,
            phase=phase,
            site=site
        ))

        # 3. Contact Form Checks (Valid & Invalid)
        contact_results = self._check_contact(
            endpoint=endpoint,
            phase=phase
        )
        results.extend(contact_results)

        # 4. Upload Check (if required by site capability)
        req_caps = site.get("requiredCapabilities", [])
        if "upload" in req_caps:
            results.append(self._check_upload_3mib(
                endpoint=endpoint,
                phase=phase
            ))

        return results

    def _check_runtime(
        self,
        endpoint: str,
        phase: str,
        expected_deployment_id: Optional[str],
        expected_php_prefix: Optional[str],
        expected_mitigation: Optional[bool]
    ) -> CheckResult:
        t0 = time.perf_counter()
        url = f"{endpoint}/runtime.php"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            php_ver = data.get("php_version", "")
            mitigation = not data.get("session_upload_progress_enabled", True)
            dep_id = data.get("deployment_id", "")

            failures = []
            if expected_php_prefix and not php_ver.startswith(expected_php_prefix):
                failures.append(f"PHP version {php_ver} does not match prefix {expected_php_prefix}")
            if expected_mitigation is not None and mitigation != expected_mitigation:
                failures.append(f"Mitigation state {mitigation} != expected {expected_mitigation}")
            if expected_deployment_id and dep_id != expected_deployment_id:
                failures.append(f"Deployment ID {dep_id} != expected {expected_deployment_id}")

            dt = (time.perf_counter() - t0) * 1000.0
            if failures:
                return CheckResult(
                    check_id="runtime_probe",
                    name="Serving Runtime & Mitigation Probe",
                    phase=phase,
                    passed=False,
                    expected={
                        "php_prefix": expected_php_prefix,
                        "mitigation": expected_mitigation,
                        "deployment_id": expected_deployment_id
                    },
                    observed=data,
                    duration_ms=round(dt, 2),
                    error_message="; ".join(failures)
                )

            return CheckResult(
                check_id="runtime_probe",
                name="Serving Runtime & Mitigation Probe",
                phase=phase,
                passed=True,
                expected={
                    "php_prefix": expected_php_prefix,
                    "mitigation": expected_mitigation,
                    "deployment_id": expected_deployment_id
                },
                observed=data,
                duration_ms=round(dt, 2)
            )

        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000.0
            return CheckResult(
                check_id="runtime_probe",
                name="Serving Runtime & Mitigation Probe",
                phase=phase,
                passed=False,
                expected="HTTP 200 JSON runtime probe",
                observed=str(e),
                duration_ms=round(dt, 2),
                error_message=f"Runtime probe request failed: {e}"
            )

    def _check_homepage(self, endpoint: str, phase: str, site: Dict[str, Any]) -> CheckResult:
        t0 = time.perf_counter()
        url = f"{endpoint}/"
        org_name = site.get("organization", site.get("name", ""))
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")

            passed = (org_name in body) and ("Contact Us" in body)
            dt = (time.perf_counter() - t0) * 1000.0
            return CheckResult(
                check_id="homepage_content",
                name="Homepage Content and Organization Title",
                phase=phase,
                passed=passed,
                expected=f"Homepage containing '{org_name}' and 'Contact Us'",
                observed="Expected elements found" if passed else "Missing organization title or links",
                duration_ms=round(dt, 2),
                error_message=None if passed else "Homepage missing organization title or navigation links"
            )
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000.0
            return CheckResult(
                check_id="homepage_content",
                name="Homepage Content and Organization Title",
                phase=phase,
                passed=False,
                expected="HTTP 200 with organization homepage",
                observed=str(e),
                duration_ms=round(dt, 2),
                error_message=f"Homepage request failed: {e}"
            )

    def _check_contact(self, endpoint: str, phase: str) -> List[CheckResult]:
        results = []
        url = f"{endpoint}/contact.php"

        # Valid submission check
        t0 = time.perf_counter()
        valid_payload = urllib.parse.urlencode({
            "name": "Verification Bot",
            "email": "verify@patchpilot.local",
            "message": "Routine automated verification check."
        }).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=valid_payload, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            passed = resp.status == 200 and data.get("valid") is True
            dt = (time.perf_counter() - t0) * 1000.0
            results.append(CheckResult(
                check_id="contact_valid",
                name="Valid Contact Form Submission",
                phase=phase,
                passed=passed,
                expected={"status": 200, "valid": True},
                observed=data,
                duration_ms=round(dt, 2),
                error_message=None if passed else "Valid contact submission did not return valid=True"
            ))
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000.0
            results.append(CheckResult(
                check_id="contact_valid",
                name="Valid Contact Form Submission",
                phase=phase,
                passed=False,
                expected={"status": 200, "valid": True},
                observed=str(e),
                duration_ms=round(dt, 2),
                error_message=f"Valid contact request failed: {e}"
            ))

        # Invalid submission check (must reject with 422)
        t0 = time.perf_counter()
        invalid_payload = urllib.parse.urlencode({
            "name": "",
            "email": "not-an-email",
            "message": ""
        }).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=invalid_payload, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    # Should have raised 422
                    passed = False
                    observed = f"Status {resp.status}"
            except urllib.error.HTTPError as he:
                passed = he.code == 422
                observed = f"HTTP {he.code}"

            dt = (time.perf_counter() - t0) * 1000.0
            results.append(CheckResult(
                check_id="contact_invalid",
                name="Invalid Contact Rejection",
                phase=phase,
                passed=passed,
                expected="HTTP 422 Unprocessable Entity",
                observed=observed,
                duration_ms=round(dt, 2),
                error_message=None if passed else "Invalid contact submission was not rejected with HTTP 422"
            ))
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000.0
            results.append(CheckResult(
                check_id="contact_invalid",
                name="Invalid Contact Rejection",
                phase=phase,
                passed=False,
                expected="HTTP 422 Unprocessable Entity",
                observed=str(e),
                duration_ms=round(dt, 2),
                error_message=f"Invalid contact request failed: {e}"
            ))

        return results

    def _check_upload_3mib(self, endpoint: str, phase: str) -> CheckResult:
        """Perform a real 3 MiB multipart upload and verify returned byte count and SHA-256."""
        t0 = time.perf_counter()
        url = f"{endpoint}/upload.php"
        exact_bytes = 3 * 1024 * 1024  # 3,145,728 bytes

        # Generate deterministic benign payload
        payload = b"PATCHPILOT_VERIFY_DATA_" * (exact_bytes // 23)
        payload += b"X" * (exact_bytes - len(payload))
        assert len(payload) == exact_bytes
        expected_sha256 = hashlib.sha256(payload).hexdigest()

        # Build multipart/form-data request
        boundary = "---------------------------PatchPilotBoundary9876543210"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="json_format"\r\n\r\n1\r\n')
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="document"; filename="health_intake_3mb.dat"\r\n')
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(payload)
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json"
        }

        try:
            req = urllib.request.Request(url, data=bytes(body), headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            bytes_received = data.get("bytes_received")
            observed_sha256 = data.get("sha256")
            passed = (
                resp.status == 200 and
                bytes_received == exact_bytes and
                observed_sha256 == expected_sha256
            )

            dt = (time.perf_counter() - t0) * 1000.0
            failures = []
            if bytes_received != exact_bytes:
                failures.append(f"Received {bytes_received} bytes != expected {exact_bytes}")
            if observed_sha256 != expected_sha256:
                failures.append(f"Hash {observed_sha256} != expected {expected_sha256}")

            return CheckResult(
                check_id="upload_3mib",
                name="3 MiB Multipart Upload Verification",
                phase=phase,
                passed=passed,
                expected={"bytes": exact_bytes, "sha256": expected_sha256},
                observed=data,
                duration_ms=round(dt, 2),
                error_message="; ".join(failures) if failures else None
            )

        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000.0
            return CheckResult(
                check_id="upload_3mib",
                name="3 MiB Multipart Upload Verification",
                phase=phase,
                passed=False,
                expected={"bytes": exact_bytes, "sha256": expected_sha256},
                observed=str(e),
                duration_ms=round(dt, 2),
                error_message=f"Upload request failed: {e}"
            )
