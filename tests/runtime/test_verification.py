"""Tests for Task 05: Verify serving runtime and application behavior."""
import subprocess
import time
import urllib.request
import pytest
from patchpilot.runtime.deployment import find_free_port
from patchpilot.runtime.verification import SiteVerifier, CheckResult

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def clinic_fixture():
    port = find_free_port()
    site_id = "test-clinic-fixture"
    tag = "patchpilot-test-clinic:v1"
    container_name = f"patchpilot-{site_id}"

    # Build image with clinic-upload-original profile (8M upload, 10M post)
    subprocess.run([
        "docker", "build",
        "-t", tag,
        "--build-arg", "BASE_IMAGE=php:8.3.35-apache",
        "--build-arg", "CONFIG_PROFILE=clinic-upload-original.ini",
        "fixtures/"
    ], check=True, capture_output=True)

    # Launch clinic fixture
    subprocess.run([
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"127.0.0.1:{port}:80",
        "-e", f"SITE_ID={site_id}",
        "-e", "ORG_NAME=St. Jude Community Clinic",
        "-e", "CAPABILITIES=homepage,contact,upload",
        "-e", "DEPLOYMENT_ID=clinic-dep-original",
        tag
    ], check=True, capture_output=True)

    endpoint = f"http://127.0.0.1:{port}"
    site_dict = {
        "id": site_id,
        "endpoint": endpoint,
        "port": port,
        "organization": "St. Jude Community Clinic",
        "requiredCapabilities": ["homepage", "contact", "upload"],
        "originalImage": "php:8.3.35-apache"
    }

    # Wait for readiness
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{endpoint}/runtime.php", timeout=2) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.5)

    yield site_dict

    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


def test_baseline_verification_passes(clinic_fixture):
    verifier = SiteVerifier()
    results = verifier.check(
        site=clinic_fixture,
        endpoint=clinic_fixture["endpoint"],
        phase="BASELINE",
        expected_deployment_id="clinic-dep-original",
        expected_php_version_prefix="8.3.35",
        expected_mitigation=False  # Original does not have mitigation applied
    )

    # Verify all checks pass
    assert len(results) == 5  # runtime, homepage, contact_valid, contact_invalid, upload_3mib
    for r in results:
        assert r.passed is True, f"Check {r.check_id} failed: {r.error_message}"

    # Verify upload check explicitly verified 3 MiB
    upload_res = next(r for r in results if r.check_id == "upload_3mib")
    assert upload_res.passed is True
    assert upload_res.observed["bytes_received"] == 3 * 1024 * 1024


def test_deliberate_homepage_mismatch_fails(clinic_fixture):
    verifier = SiteVerifier()
    tampered_site = dict(clinic_fixture)
    tampered_site["organization"] = "Non-existent Organization X"

    results = verifier.check(
        site=tampered_site,
        endpoint=clinic_fixture["endpoint"],
        phase="BASELINE"
    )

    hp_res = next(r for r in results if r.check_id == "homepage_content")
    assert hp_res.passed is False
    assert "Missing organization title" in hp_res.error_message or "missing" in hp_res.error_message.lower()


def test_deliberate_deployment_id_mismatch_fails(clinic_fixture):
    verifier = SiteVerifier()
    results = verifier.check(
        site=clinic_fixture,
        endpoint=clinic_fixture["endpoint"],
        phase="CANDIDATE",
        expected_deployment_id="wrong-deployment-id-999"
    )

    probe_res = next(r for r in results if r.check_id == "runtime_probe")
    assert probe_res.passed is False
    assert "wrong-deployment-id-999" in probe_res.error_message


def test_deliberate_mitigation_expectation_mismatch_fails(clinic_fixture):
    verifier = SiteVerifier()
    # Expect mitigation=True on unpatched original fixture
    results = verifier.check(
        site=clinic_fixture,
        endpoint=clinic_fixture["endpoint"],
        phase="CANDIDATE",
        expected_mitigation=True
    )

    probe_res = next(r for r in results if r.check_id == "runtime_probe")
    assert probe_res.passed is False
    assert "Mitigation state" in probe_res.error_message
