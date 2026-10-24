"""Strict serving-runtime and application verification for registered fixtures."""

from __future__ import annotations

import hashlib
import http.client
import json
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from patchpilot.core.domain import CheckResult, DeploymentSnapshot, Site
from patchpilot.runtime.deadline import Deadline

if TYPE_CHECKING:
    from patchpilot.runtime.bridge import DockerRuntime


class HttpVerifier:
    """Seven/nine unchanged assertions using actual serving HTTP responses."""

    def __init__(self, runtime: DockerRuntime):
        self.runtime = runtime

    @staticmethod
    def upload_payload() -> bytes:
        size = 3 * 1024 * 1024
        seed = b"PATCHPILOT_VERIFY_DATA_"
        return (seed * (size // len(seed))) + b"X" * (size % len(seed))

    def check(
        self, site: Site, snapshot: DeploymentSnapshot, phase: str, *, timeout_s: float
    ) -> tuple[CheckResult, ...]:
        entry = self.runtime._site(site)
        if (
            phase not in {"BASELINE", "STAGING", "LIVE", "RESTORATION"}
            or snapshot.site_id != site.site_id
        ):
            raise ValueError("Invalid verification phase or registered site")
        endpoint = snapshot.base_url
        if phase != "STAGING" and endpoint != site.base_url:
            raise ValueError("Verification endpoint differs from the registered site")
        if phase == "STAGING" and endpoint == site.base_url:
            raise ValueError("Staging verification requires an isolated endpoint")
        deadline = Deadline(timeout_s)
        checks: list[CheckResult] = []

        def append(
            check_id: str, passed: bool, expected: Any, observed: Any, started: float
        ) -> None:
            def scalar(value: Any) -> str | int | bool | None:
                if isinstance(value, str):
                    return value[:512]
                return value if type(value) in {int, bool} else None

            checks.append(
                CheckResult(
                    check_id,
                    passed is True,
                    "Assertion passed" if passed else "Required HTTP assertion failed",
                    phase,
                    site.site_id,
                    round((time.monotonic() - started) * 1000, 2),
                    scalar(expected),
                    scalar(observed),
                )
            )

        started = time.monotonic()
        try:
            probe = self.runtime._probe(endpoint, deadline)
        except (OSError, ValueError, RuntimeError, http.client.HTTPException):
            probe = {}
        version = probe.get("php_version")
        progress = probe.get("session_upload_progress_enabled")
        expected_version = (
            "8.3.36" if phase in {"STAGING", "LIVE"} else snapshot.php_version
        )
        expected_progress = (
            False if phase in {"STAGING", "LIVE"} else snapshot.upload_progress_enabled
        )
        append(
            "runtime_version",
            isinstance(version, str) and version == expected_version,
            expected_version,
            version if isinstance(version, str) else None,
            started,
        )
        append(
            "sapi",
            probe.get("php_sapi") == "apache2handler"
            and snapshot.sapi == "apache2handler",
            "apache2handler",
            probe.get("php_sapi"),
            started,
        )
        append(
            "upload_progress",
            type(progress) is bool and progress is expected_progress,
            expected_progress,
            progress if type(progress) is bool else None,
            started,
        )
        append(
            "deployment_identity",
            probe.get("status") == "ok"
            and probe.get("site_id") == site.site_id
            and probe.get("deployment_id") == snapshot.deployment_id,
            snapshot.deployment_id,
            probe.get("deployment_id"),
            started,
        )
        started = time.monotonic()
        try:
            status, body = self.runtime._request(endpoint, "/", deadline)
            content = body.decode("utf-8")
            homepage = (
                status == 200
                and entry["organization"] in content
                and "Contact Us" in content
            )
        except (OSError, ValueError, http.client.HTTPException):
            homepage = False
        append(
            "homepage",
            homepage,
            entry["organization"],
            "Expected content found" if homepage else None,
            started,
        )
        for valid in (True, False):
            started = time.monotonic()
            fields = (
                {
                    "name": "Verification Bot",
                    "email": "verify@patchpilot.local",
                    "message": "Routine verification.",
                }
                if valid
                else {"name": "", "email": "not-an-email", "message": ""}
            )
            try:
                status, body = self.runtime._request(
                    endpoint,
                    "/contact.php",
                    deadline,
                    method="POST",
                    body=urlencode(fields).encode(),
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                data = json.loads(body)
                passed = (
                    status == (200 if valid else 422)
                    and isinstance(data, dict)
                    and data.get("valid") is valid
                )
                if not valid:
                    passed = (
                        passed
                        and isinstance(data.get("errors"), dict)
                        and {"name", "email", "message"} <= set(data["errors"])
                    )
            except (OSError, ValueError, http.client.HTTPException):
                passed = False
            append(
                "contact_valid" if valid else "contact_invalid",
                passed,
                200 if valid else 422,
                "Expected response" if passed else None,
                started,
            )
        if "upload" in site.capabilities:
            started = time.monotonic()
            payload = self.upload_payload()
            expected_hash = hashlib.sha256(payload).hexdigest()
            boundary = "PatchPilotVerificationBoundary9876543210"
            body = (
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="verification.dat"\r\n'
                    "Content-Type: application/octet-stream\r\n\r\n"
                ).encode()
                + payload
                + f"\r\n--{boundary}--\r\n".encode()
            )
            try:
                status, response = self.runtime._request(
                    endpoint,
                    "/upload.php",
                    deadline,
                    method="POST",
                    body=body,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                    },
                )
                data = json.loads(response)
                if not isinstance(data, dict) or status != 200:
                    data = {}
            except (OSError, ValueError, http.client.HTTPException):
                data = {}
            size, observed_hash = data.get("bytes_received"), data.get("sha256")
            append(
                "upload_size",
                type(size) is int and size == len(payload),
                len(payload),
                size if type(size) is int else None,
                started,
            )
            append(
                "upload_hash",
                isinstance(observed_hash, str) and observed_hash == expected_hash,
                expected_hash,
                observed_hash if isinstance(observed_hash, str) else None,
                started,
            )
        return tuple(checks)
