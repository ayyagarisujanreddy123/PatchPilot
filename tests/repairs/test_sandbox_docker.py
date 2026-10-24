"""Actual disconnected PHP execution; needs only the dedicated local Docker engine."""

from pathlib import Path

import pytest

from patchpilot.repairs.models import SiteManifest
from patchpilot.repairs.sandbox import REQUIRED_SECURITY_CHECKS, DockerSandbox

pytestmark = pytest.mark.docker
ROOT = Path(__file__).resolve().parents[2]


def source_files():
    return {
        name: (ROOT / "fixtures" / "site" / name).read_bytes()
        for name in ("index.php", "contact.php", "upload.php")
    }


def test_actual_baseline_and_candidate_business_and_security(tmp_path):
    manifest = SiteManifest(
        site_id="owned-demo-site",
        document_root="public",
        php_ini="config/php.ini",
        capabilities=["homepage", "contact", "upload"],
    )
    base = "upload_max_filesize=8M\npost_max_size=10M\nmemory_limit=128M\n"
    insecure = (
        "display_errors=On\ndisplay_startup_errors=On\nlog_errors=Off\nexpose_php=On\n"
    )
    secure = "display_errors=Off\ndisplay_startup_errors=Off\nlog_errors=On\nexpose_php=Off\n"
    sandbox = DockerSandbox(tmp_path)
    baseline = sandbox.verify(
        source_files(),
        base + insecure,
        manifest,
        ["homepage", "contact", "upload"],
        "BASELINE",
        run_id="docker-acceptance-baseline",
    )
    candidate = sandbox.verify(
        source_files(),
        base + secure,
        manifest,
        ["homepage", "contact", "upload"],
        "CANDIDATE",
        run_id="docker-acceptance-candidate",
    )
    assert {
        check.check_id for check in baseline.checks if not check.passed
    } == REQUIRED_SECURITY_CHECKS
    assert all(check.passed for check in candidate.checks)
    assert all(check.phase == "BASELINE" for check in baseline.checks)
    assert all(check.phase == "CANDIDATE" for check in candidate.checks)
    assert baseline.image_digest == candidate.image_digest
    assert candidate.runtime["php_version"] == "8.3.36"
    upload = next(
        check for check in candidate.checks if check.check_id == "upload_sha256"
    )
    assert upload.expected == upload.observed and len(upload.expected) == 64
    assert not list((tmp_path / "var" / "repair-sandboxes").glob("job-*"))


def test_upload_limit_regression_is_observed_not_relaxed(tmp_path):
    manifest = SiteManifest(
        site_id="owned-demo-site",
        document_root="public",
        php_ini="config/php.ini",
        capabilities=["homepage", "upload"],
    )
    result = DockerSandbox(tmp_path).verify(
        source_files(),
        "upload_max_filesize=2M\npost_max_size=8M\ndisplay_errors=Off\ndisplay_startup_errors=Off\nlog_errors=On\nexpose_php=Off\n",
        manifest,
        ["homepage", "upload"],
        "CANDIDATE",
        run_id="docker-upload-rejection",
    )
    checks = {check.check_id: check for check in result.checks}
    assert checks["homepage_status"].passed
    assert not checks["upload_size"].passed
    assert not checks["upload_sha256"].passed


def test_untrusted_app_cannot_write_trusted_files_spawn_or_read_host_process_environment(
    tmp_path,
):
    manifest = SiteManifest(
        site_id="owned-demo-site",
        document_root="public",
        php_ini="config/php.ini",
        capabilities=["homepage"],
    )
    app = b"""<?php
    $blocked = !function_exists('exec') && !function_exists('proc_open') && !function_exists('posix_kill')
        && !is_writable('/sandbox/router.php') && !is_writable('/app/index.php')
        && @file_get_contents('/proc/self/environ') === false;
    http_response_code($blocked ? 200 : 500);
    echo $blocked ? 'sandbox restrictions hold' : 'sandbox restrictions failed';
    """
    result = DockerSandbox(tmp_path).verify(
        {"index.php": app},
        "display_errors=Off\ndisplay_startup_errors=Off\nlog_errors=On\nexpose_php=Off\n",
        manifest,
        ["homepage"],
        "CANDIDATE",
        run_id="docker-isolation",
    )
    assert all(check.passed for check in result.checks)
