"""Fixed sandbox boundary tests; Docker is replaced only at its process boundary."""

import json
import subprocess
from pathlib import Path

import pytest

from patchpilot.repairs.models import SiteManifest
from patchpilot.repairs.sandbox import (
    BUSINESS_CHECKS,
    REQUIRED_SECURITY_CHECKS,
    DockerSandbox,
    SandboxError,
)


@pytest.fixture
def manifest():
    return SiteManifest(
        site_id="owned-demo-site",
        document_root="public",
        php_ini="config/php.ini",
        capabilities=["homepage", "contact", "upload"],
    )


@pytest.mark.parametrize(
    "name",
    [
        "../index.php",
        "/index.php",
        "a/../../index.php",
        "a\\index.php",
        "a//index.php",
        ".env",
        "a/.env.local",
        ".git/config",
    ],
)
def test_unsafe_source_rejected_before_docker(tmp_path, manifest, name):
    sandbox = DockerSandbox(tmp_path)
    sandbox._docker = lambda *args, **kwargs: pytest.fail(
        "Unsafe source reached Docker"
    )
    with pytest.raises(SandboxError, match="source"):
        sandbox.verify(
            {name: b"<?php echo 'secret';"},
            "",
            manifest,
            ["homepage"],
            "BASELINE",
            run_id="repair-test",
        )


@pytest.mark.parametrize(
    "ini",
    [
        "auto_prepend_file=/app/hook.php",
        "extension=evil.so",
        "[PATH=/app]\ndisplay_errors=Off",
        "expose_php=${SECRET}",
        "expose_php=Off\nexpose_php=On",
        "display_errors=Off\x00",
    ],
)
def test_unsupported_ini_rejected_before_docker(tmp_path, manifest, ini):
    sandbox = DockerSandbox(tmp_path)
    sandbox._docker = lambda *args, **kwargs: pytest.fail("Unsafe INI reached Docker")
    with pytest.raises(SandboxError, match="configuration"):
        sandbox.verify(
            {"index.php": b"<?php echo 'ok';"},
            ini,
            manifest,
            ["homepage"],
            "BASELINE",
            run_id="repair-test",
        )


@pytest.mark.parametrize(
    "capabilities", [[], ["contact"], ["homepage", "homepage"], ["homepage", "shell"]]
)
def test_checks_must_be_explicit_unique_supported_capabilities(
    tmp_path, manifest, capabilities
):
    with pytest.raises(SandboxError, match="capabilities"):
        DockerSandbox(tmp_path).verify(
            {"index.php": b"ok"},
            "",
            manifest,
            capabilities,
            "BASELINE",
            run_id="repair-test",
        )


def test_source_and_configuration_limits(tmp_path, manifest):
    sandbox = DockerSandbox(tmp_path)
    for files, ini in [
        ({"index.php": b"x" * (256 * 1024 + 1)}, ""),
        ({f"file-{i}.php": b"x" for i in range(101)}, ""),
        ({f"file-{i}.php": b"x" * (256 * 1024) for i in range(17)}, ""),
        ({"index.php": b"ok"}, ";" * (16 * 1024 + 1)),
    ]:
        with pytest.raises(SandboxError):
            sandbox.verify(
                files, ini, manifest, ["homepage"], "BASELINE", run_id="repair-test"
            )


def result_document(phase="CANDIDATE"):
    return {
        "runtime": {
            "php_version": "8.3.36",
            "display_errors": False,
            "display_startup_errors": False,
            "log_errors": True,
            "expose_php": False,
        },
        "identity": {
            "sapi": "cli-server",
            "site_id": "owned-demo-site",
            "phase": phase,
        },
        "observations": {
            "banner_hidden": True,
            "homepage_status": 200,
            "contact_valid": {"status": 200, "valid": True, "errors_empty": True},
            "contact_invalid": {"status": 422, "valid": False, "required_errors": True},
            "upload": {
                "status": 200,
                "bytes_received": 3145728,
                "expected_bytes": 3145728,
                "sha256_matches": True,
                "expected_sha256": "d" * 64,
                "sha256": "d" * 64,
            },
        },
        "durations_ms": {
            "runtime": 1,
            "homepage": 2,
            "contact_valid": 3,
            "contact_invalid": 4,
            "upload": 5,
        },
    }


class FakeDockerSandbox(DockerSandbox):
    def __init__(self, root, document=None):
        super().__init__(root)
        self.document = document or result_document()
        self.commands = []
        self.context_files = {}
        self.labels = {}
        self.container_labels = {}
        self.image_exists = False
        self.container_exists = False
        self.tamper_owner = False
        self.exec_failure = False

    def _docker(self, arguments, deadline, *, check=True):
        self.commands.append(arguments)
        output, code = "", 0
        if arguments[:2] == ["image", "inspect"]:
            if arguments[-1].startswith("docker.io/library/php@sha256:"):
                output = json.dumps(
                    [
                        {
                            "Id": "sha256:" + "a" * 64,
                            "Os": "linux",
                            "Architecture": "arm64",
                        }
                    ]
                )
            elif self.image_exists:
                output = json.dumps(
                    [{"Id": "sha256:" + "b" * 64, "Config": {"Labels": self.labels}}]
                )
            else:
                code = 1
        elif arguments[0] == "version":
            output = "linux/arm64"
        elif arguments[0] == "build":
            self.labels = dict(
                arguments[i + 1].split("=", 1)
                for i, value in enumerate(arguments)
                if value == "--label"
            )
            context = Path(arguments[-1])
            self.context_files = {
                p.relative_to(context).as_posix(): p.read_bytes()
                for p in context.rglob("*")
                if p.is_file()
            }
            self.image_exists = True
        elif arguments[0] == "run":
            self.container_labels = dict(
                arguments[i + 1].split("=", 1)
                for i, value in enumerate(arguments)
                if value == "--label"
            )
            self.container_exists = True
            output = "c" * 64
        elif arguments[0] == "exec":
            if self.exec_failure:
                raise SandboxError("Sandbox command failed")
            output = json.dumps(self.document)
        elif arguments[0] == "inspect":
            if self.container_exists:
                labels = dict(self.container_labels)
                if self.tamper_owner:
                    labels["patchpilot.sandbox.owner"] = "somebody-else"
                output = json.dumps([{"Id": "c" * 64, "Config": {"Labels": labels}}])
            else:
                code = 1
        elif arguments[0] == "rm":
            self.container_exists = False
        elif arguments[:2] == ["image", "rm"]:
            self.image_exists = False
        else:
            raise AssertionError(arguments)
        if check and code:
            raise SandboxError("Sandbox command failed")
        return subprocess.CompletedProcess(arguments, code, output, "")


def test_complete_result_has_fixed_checks_and_no_raw_observations(tmp_path, manifest):
    sandbox = FakeDockerSandbox(tmp_path)
    result = sandbox.verify(
        {"index.php": b"<?php echo 'ok';"},
        "upload_max_filesize=8M\n",
        manifest,
        ["homepage", "contact", "upload"],
        "CANDIDATE",
        run_id="repair-test",
    )
    expected = (
        REQUIRED_SECURITY_CHECKS
        | {"runtime_version"}
        | set().union(*BUSINESS_CHECKS.values())
    )
    assert {item.check_id for item in result.checks} == expected
    assert all(item.passed and item.phase == "CANDIDATE" for item in result.checks)
    assert result.runtime == result_document()["runtime"]
    assert all(item.duration_ms >= 0 for item in result.checks)
    assert not sandbox.container_exists and not sandbox.image_exists
    assert not list((tmp_path / "var" / "repair-sandboxes").glob("job-*"))


def test_baseline_records_security_failure_without_hiding_business_pass(
    tmp_path, manifest
):
    document = result_document("BASELINE")
    document["runtime"]["display_errors"] = True
    document["observations"]["banner_hidden"] = False
    sandbox = FakeDockerSandbox(tmp_path, document)
    result = sandbox.verify(
        {"index.php": b"ok"},
        "",
        manifest,
        ["homepage"],
        "BASELINE",
        run_id="repair-test",
    )
    checks = {item.check_id: item for item in result.checks}
    assert not checks["display_errors"].passed
    assert not checks["php_banner_hidden"].passed
    assert checks["homepage_status"].passed
    assert "contact_valid" not in checks


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["runtime"].update(expose_php=0),
        lambda d: d["runtime"].update(php_version="8.3.35"),
        lambda d: d["identity"].update(sapi="cli"),
        lambda d: d["identity"].update(site_id="different-site"),
        lambda d: d["observations"].pop("homepage_status"),
    ],
)
def test_incomplete_or_forged_verifier_output_fails_closed_and_cleans(
    tmp_path, manifest, change
):
    document = result_document()
    change(document)
    sandbox = FakeDockerSandbox(tmp_path, document)
    with pytest.raises(SandboxError):
        sandbox.verify(
            {"index.php": b"ok"},
            "",
            manifest,
            ["homepage"],
            "CANDIDATE",
            run_id="repair-test",
        )
    assert not sandbox.container_exists and not sandbox.image_exists


def test_container_isolated_and_only_trusted_build_instructions(tmp_path, manifest):
    sandbox = FakeDockerSandbox(tmp_path)
    sandbox.verify(
        {"index.php": b"ok", "Dockerfile": b"RUN steal-all-secrets"},
        "",
        manifest,
        ["homepage"],
        "CANDIDATE",
        run_id="repair-test",
    )
    command = next(command for command in sandbox.commands if command[0] == "run")
    for flag, value in [
        ("--network", "none"),
        ("--user", "65532:65532"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--pids-limit", "32"),
        ("--memory", "256m"),
    ]:
        assert command[command.index(flag) + 1] == value
    assert "--read-only" in command
    assert not (
        {"-p", "--publish", "--privileged", "-v", "--volume", "--env-file"}
        & set(command)
    )
    dockerfile = sandbox.context_files["Dockerfile"].decode()
    assert "RUN " not in dockerfile
    assert "@sha256:" in dockerfile
    assert sandbox.context_files["app/Dockerfile"] == b"RUN steal-all-secrets"
    execute = next(command for command in sandbox.commands if command[0] == "exec")
    assert execute[execute.index("--user") + 1] == "65533:65533"
    assert "-n" in execute


def test_cleanup_refuses_another_owners_container(tmp_path, manifest):
    sandbox = FakeDockerSandbox(tmp_path)
    sandbox.tamper_owner = True
    with pytest.raises(SandboxError, match="cleanup"):
        sandbox.verify(
            {"index.php": b"ok"},
            "",
            manifest,
            ["homepage"],
            "CANDIDATE",
            run_id="repair-test",
        )
    assert not any(command[0] == "rm" for command in sandbox.commands)


def test_command_failure_still_removes_only_owned_resources(tmp_path, manifest):
    sandbox = FakeDockerSandbox(tmp_path)
    sandbox.exec_failure = True
    with pytest.raises(SandboxError):
        sandbox.verify(
            {"index.php": b"ok"},
            "",
            manifest,
            ["homepage"],
            "CANDIDATE",
            run_id="repair-test",
        )
    assert not sandbox.container_exists and not sandbox.image_exists
