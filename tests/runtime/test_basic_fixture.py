"""Basic fixture tests for Task 03 acceptance criteria."""
import json
import socket
import subprocess
import time
import urllib.request
import urllib.parse
import urllib.error
import pytest

pytestmark = pytest.mark.docker


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def basic_fixture():
    port = get_free_port()
    tag = "patchpilot-test-fixture:basic-fixture-test"
    container_name = f"patchpilot-test-container-{port}"

    # Build image
    build_cmd = [
        "docker", "build",
        "-t", tag,
        "--build-arg", "BASE_IMAGE=php:8.3.35-apache",
        "--build-arg", "CONFIG_PROFILE=pantry-default.ini",
        "fixtures/"
    ]
    subprocess.run(build_cmd, check=True, capture_output=True)

    # Run container
    run_cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"127.0.0.1:{port}:80",
        "-e", "SITE_ID=pantry-test",
        "-e", "ORG_NAME=Test Food Pantry",
        "-e", "DEPLOYMENT_ID=dep-test-123",
        tag
    ]
    subprocess.run(run_cmd, check=True, capture_output=True)

    endpoint = f"http://127.0.0.1:{port}"

    # Wait for readiness
    ready = False
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{endpoint}/runtime.php", timeout=2) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.5)

    if not ready:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        raise RuntimeError("Fixture container failed to become ready within deadline")

    yield {
        "endpoint": endpoint,
        "container_name": container_name,
        "port": port
    }

    # Teardown
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


def test_runtime_probe(basic_fixture):
    endpoint = basic_fixture["endpoint"]
    req = urllib.request.Request(f"{endpoint}/runtime.php")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))

    assert data["status"] == "ok"
    assert data["php_version"].startswith("8.3.35")
    assert "apache" in data["php_sapi"].lower()
    assert data["deployment_id"] == "dep-test-123"
    assert data["site_id"] == "pantry-test"
    assert data["organization"] == "Test Food Pantry"
    assert data["session_upload_progress_enabled"] is True


def test_homepage(basic_fixture):
    endpoint = basic_fixture["endpoint"]
    with urllib.request.urlopen(f"{endpoint}/", timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")

    assert "Test Food Pantry" in body
    assert "Contact Us" in body
    assert "Serving Status" in body


def test_contact_validation_valid(basic_fixture):
    endpoint = basic_fixture["endpoint"]
    payload = urllib.parse.urlencode({
        "name": "Jane Doe",
        "email": "jane@example.com",
        "message": "Valid volunteer inquiry message."
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{endpoint}/contact.php",
        data=payload,
        headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["valid"] is True
        assert "received" in data["message"]


def test_contact_validation_invalid(basic_fixture):
    endpoint = basic_fixture["endpoint"]
    payload = urllib.parse.urlencode({
        "name": "",
        "email": "invalid-email",
        "message": "hi"
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{endpoint}/contact.php",
        data=payload,
        headers={"Accept": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)

    assert exc_info.value.code == 422
    data = json.loads(exc_info.value.read().decode("utf-8"))
    assert data["valid"] is False
    assert "name" in data["errors"]
    assert "email" in data["errors"]
    assert "message" in data["errors"]
