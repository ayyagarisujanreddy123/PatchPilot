"""Tests for Task 04: staging immutable candidates through DockerRuntimeAdapter."""
import subprocess
import time
import urllib.request
import pytest
from patchpilot.runtime.deployment import DockerRuntimeAdapter, find_free_port


@pytest.fixture(scope="module")
def runtime_adapter():
    return DockerRuntimeAdapter()


@pytest.fixture(scope="module")
def live_original_site(runtime_adapter):
    port = find_free_port()
    site_id = "test-orig-site"
    tag = "patchpilot-test-original:v1"
    container_name = f"patchpilot-{site_id}"

    # Build original image
    subprocess.run([
        "docker", "build",
        "-t", tag,
        "--build-arg", "BASE_IMAGE=php:8.3.35-apache",
        "--build-arg", "CONFIG_PROFILE=pantry-default.ini",
        "fixtures/"
    ], check=True, capture_output=True)

    # Launch original container
    subprocess.run([
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"127.0.0.1:{port}:80",
        "-e", f"SITE_ID={site_id}",
        "-e", "ORG_NAME=Original Pantry",
        "-e", "DEPLOYMENT_ID=orig-dep-001",
        tag
    ], check=True, capture_output=True)

    endpoint = f"http://127.0.0.1:{port}"
    site_dict = {
        "id": site_id,
        "endpoint": endpoint,
        "port": port,
        "organization": "Original Pantry",
        "requiredCapabilities": ["homepage", "contact"],
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

    # Teardown
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
    subprocess.run(["docker", "rm", "-f", f"patchpilot-orig-retained-{site_id}"], capture_output=True)


def test_inspect_original(runtime_adapter, live_original_site):
    snapshot = runtime_adapter.inspect(live_original_site)
    assert snapshot.site_id == live_original_site["id"]
    assert snapshot.php_version.startswith("8.3.35")
    assert "apache" in snapshot.php_sapi.lower()
    assert snapshot.session_upload_progress_enabled is True
    assert snapshot.deployment_id == "orig-dep-001"


def test_stage_candidate_while_original_keeps_serving(runtime_adapter, live_original_site):
    orig_endpoint = live_original_site["endpoint"]

    # Stage a candidate using patched image and repaired configuration
    candidate = runtime_adapter.stage(
        site=live_original_site,
        base_image="php:8.3.36-apache",
        config_profile="pantry-repaired.ini",
        run_id="run-001",
        attempt=1
    )

    try:
        # 1. Check candidate endpoint
        cand_resp = urllib.request.urlopen(f"{candidate.endpoint}/runtime.php", timeout=5)
        assert cand_resp.status == 200

        # 2. Confirm original site remains available concurrently
        orig_resp = urllib.request.urlopen(f"{orig_endpoint}/runtime.php", timeout=5)
        assert orig_resp.status == 200

        # Verify candidate runtime reflects candidate settings
        import json
        cand_data = json.loads(cand_resp.read().decode("utf-8"))
        assert cand_data["php_version"].startswith("8.3.36")
        assert cand_data["session_upload_progress_enabled"] is False

    finally:
        # Clean up candidate
        clean_res = runtime_adapter.cleanup(candidate)
        assert clean_res["cleaned"] is True


def test_activate_and_restore(runtime_adapter, live_original_site):
    # Stage candidate
    candidate = runtime_adapter.stage(
        site=live_original_site,
        base_image="php:8.3.36-apache",
        config_profile="pantry-repaired.ini",
        run_id="run-002",
        attempt=1
    )

    try:
        # Activate candidate at original port
        live_snapshot = runtime_adapter.activate(live_original_site, candidate)
        assert live_snapshot.php_version.startswith("8.3.36")
        assert live_snapshot.session_upload_progress_enabled is False

        # Now test restore: roll back to retained original
        restored_snapshot = runtime_adapter.restore(live_original_site)
        assert restored_snapshot.php_version.startswith("8.3.35")
        assert restored_snapshot.session_upload_progress_enabled is True
        assert restored_snapshot.deployment_id == "orig-dep-001"

    finally:
        runtime_adapter.cleanup(candidate)
