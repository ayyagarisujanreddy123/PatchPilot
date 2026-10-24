"""Tests for Task 07: Verify the real 3 MiB upload capability and failure under 2M limit."""
import hashlib
import json
import subprocess
import time
import urllib.request
import pytest
from patchpilot.runtime.deployment import find_free_port
from patchpilot.runtime.verification import SiteVerifier


@pytest.fixture(scope="module")
def upload_fixtures():
    """Starts both an 8M/10M clinic fixture and a 2M flawed clinic fixture."""
    port_8m = find_free_port()
    port_2m = find_free_port()

    # Build image with 8M profile
    subprocess.run([
        "docker", "build", "-t", "patchpilot-test-clinic-8m:v1",
        "--build-arg", "BASE_IMAGE=php:8.3.35-apache",
        "--build-arg", "CONFIG_PROFILE=clinic-upload-original.ini",
        "fixtures/"
    ], check=True, capture_output=True)

    # Build image with 2M profile
    subprocess.run([
        "docker", "build", "-t", "patchpilot-test-clinic-2m:v1",
        "--build-arg", "BASE_IMAGE=php:8.3.36-apache",
        "--build-arg", "CONFIG_PROFILE=clinic-upload-flawed.ini",
        "fixtures/"
    ], check=True, capture_output=True)

    # Launch 8M container
    c_8m = f"patchpilot-test-upload-8m-{port_8m}"
    subprocess.run([
        "docker", "run", "-d", "--name", c_8m,
        "-p", f"127.0.0.1:{port_8m}:80",
        "-e", "SITE_ID=clinic-8m",
        "-e", "ORG_NAME=8M Clinic",
        "-e", "CAPABILITIES=homepage,contact,upload",
        "-e", "DEPLOYMENT_ID=dep-8m",
        "patchpilot-test-clinic-8m:v1"
    ], check=True, capture_output=True)

    # Launch 2M container
    c_2m = f"patchpilot-test-upload-2m-{port_2m}"
    subprocess.run([
        "docker", "run", "-d", "--name", c_2m,
        "-p", f"127.0.0.1:{port_2m}:80",
        "-e", "SITE_ID=clinic-2m",
        "-e", "ORG_NAME=2M Clinic",
        "-e", "CAPABILITIES=homepage,contact,upload",
        "-e", "DEPLOYMENT_ID=dep-2m",
        "patchpilot-test-clinic-2m:v1"
    ], check=True, capture_output=True)

    # Wait for readiness
    for endpoint in [f"http://127.0.0.1:{port_8m}", f"http://127.0.0.1:{port_2m}"]:
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{endpoint}/runtime.php", timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.5)

    yield {
        "8m_endpoint": f"http://127.0.0.1:{port_8m}",
        "2m_endpoint": f"http://127.0.0.1:{port_2m}",
        "c_8m": c_8m,
        "c_2m": c_2m
    }

    subprocess.run(["docker", "rm", "-f", c_8m], capture_output=True)
    subprocess.run(["docker", "rm", "-f", c_2m], capture_output=True)


def test_3mib_upload_succeeds_on_8m_profile(upload_fixtures):
    verifier = SiteVerifier()
    site = {
        "id": "clinic-8m",
        "organization": "8M Clinic",
        "requiredCapabilities": ["homepage", "contact", "upload"]
    }
    result = verifier._check_upload_3mib(
        endpoint=upload_fixtures["8m_endpoint"],
        phase="BASELINE"
    )

    assert result.passed is True
    assert result.observed["bytes_received"] == 3 * 1024 * 1024
    assert result.observed["sha256"] is not None


def test_3mib_upload_fails_on_2m_profile(upload_fixtures):
    verifier = SiteVerifier()
    site = {
        "id": "clinic-2m",
        "organization": "2M Clinic",
        "requiredCapabilities": ["homepage", "contact", "upload"]
    }
    result = verifier._check_upload_3mib(
        endpoint=upload_fixtures["2m_endpoint"],
        phase="CANDIDATE"
    )

    # 3 MiB exceeds the 2M limit, so upload check must fail
    assert result.passed is False
    assert result.error_message is not None
