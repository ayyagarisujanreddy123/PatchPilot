"""Run fixed HTTP checks against a bounded, disconnected PHP reconstruction.

Repository bytes are copied by a trusted Dockerfile; no repository build command
is executed. Only scalar observations produced by the bundled verifier leave the
sandbox. The host's Docker context is inherited without changing global state.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath

from .models import SandboxResult, SiteManifest, VerificationCheck

REQUIRED_SECURITY_CHECKS = frozenset(
    {
        "display_errors",
        "display_startup_errors",
        "log_errors",
        "expose_php",
        "php_banner_hidden",
    }
)
BUSINESS_CHECKS = {
    "homepage": frozenset({"homepage_status"}),
    "contact": frozenset({"contact_valid", "contact_invalid"}),
    "upload": frozenset({"upload_size", "upload_sha256"}),
}
PHP_VERSION = "8.3.36"
# Official docker.io/library/php:8.3.36-apache platform manifests, verified against
# Docker Hub's manifest index. Tags are never accepted as execution identities.
BASE_DIGESTS = {
    "linux/arm64": "sha256:cfe23687444ee5e3335f37390b8feb1142804d7bbf4d54fa59f199b6afeb9b97",
    "linux/amd64": "sha256:2f3bc298d62723e0d0c03986556abb8d8aa584a9c217c934fa00def064c76f3c",
}
_INI_KEYS = REQUIRED_SECURITY_CHECKS - {"php_banner_hidden"} | {
    "upload_max_filesize",
    "post_max_size",
    "memory_limit",
    "max_execution_time",
    "date.timezone",
    "error_reporting",
    "session.upload_progress.enabled",
}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_ASSETS = Path(__file__).with_name("sandbox_assets")
_DISABLED_FUNCTIONS = "exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec,pcntl_fork,posix_kill,dl,putenv"


class SandboxError(RuntimeError):
    """Safe operational error: never contains app output, source or host paths."""


class _Deadline:
    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def remaining(self, maximum: float = 90) -> float:
        value = min(maximum, self.end - time.monotonic())
        if value <= 0:
            raise SandboxError("Sandbox verification deadline exceeded")
        return value


def _validate_inputs(files, ini_content, manifest, capabilities, phase, run_id):
    if (
        phase not in {"BASELINE", "CANDIDATE"}
        or not isinstance(run_id, str)
        or not 1 <= len(run_id) <= 160
        or any(ord(c) < 32 for c in run_id)
    ):
        raise SandboxError("Invalid sandbox verification identity")
    if not isinstance(manifest, SiteManifest):
        raise SandboxError("Invalid sandbox manifest")
    if (
        not isinstance(capabilities, list)
        or "homepage" not in capabilities
        or len(capabilities) != len(set(capabilities))
        or not set(capabilities) <= set(manifest.capabilities)
    ):
        raise SandboxError("Invalid sandbox capabilities")
    if not isinstance(files, dict) or not files or len(files) > 100:
        raise SandboxError("Sandbox source exceeds supported limits")
    total = 0
    folded = set()
    for name, content in files.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name)
            or len(name) > 200
        ):
            raise SandboxError("Unsafe sandbox source path")
        parts = PurePosixPath(name).parts
        if (
            any(
                part.lower() in {".", "..", ".git"} or part.lower().startswith(".env")
                for part in parts
            )
            or name.casefold() in folded
        ):
            raise SandboxError("Unsafe sandbox source path")
        folded.add(name.casefold())
        if type(content) is not bytes or len(content) > 256 * 1024:
            raise SandboxError("Sandbox source exceeds supported limits")
        total += len(content)
    if total > 4 * 1024 * 1024:
        raise SandboxError("Sandbox source exceeds supported limits")
    if (
        not isinstance(ini_content, str)
        or len(ini_content.encode("utf-8")) > 16 * 1024
        or any(ord(c) < 32 and c not in "\n\r\t" for c in ini_content)
    ):
        raise SandboxError("Unsupported sandbox PHP configuration")
    seen = set()
    for line in ini_content.splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        match = re.fullmatch(
            r'([a-z_.]+)\s*=\s*("?[A-Za-z0-9_./+|()~ -]+"?)\s*(?:;[^\r\n]*)?', line
        )
        if not match or match[1] not in _INI_KEYS or match[1] in seen:
            raise SandboxError("Unsupported sandbox PHP configuration")
        value = match[2].strip()
        if value.startswith('"') != value.endswith('"'):
            raise SandboxError("Unsupported sandbox PHP configuration")
        seen.add(match[1])


class DockerSandbox:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or Path.cwd()).resolve()
        self.owner = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
        self.timeout_s = 90.0

    def _docker(self, arguments: list[str], deadline: _Deadline, *, check=True):
        try:
            result = subprocess.run(
                ["docker", *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=deadline.remaining(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise SandboxError("Sandbox verification deadline exceeded") from None
        except (OSError, ValueError):
            raise SandboxError("The Docker sandbox is unavailable") from None
        if len(result.stdout) > 128 * 1024 or len(result.stderr) > 256 * 1024:
            raise SandboxError("Sandbox command output exceeded its limit")
        if check and result.returncode:
            raise SandboxError(
                "Sandbox command failed; no untrusted output was retained"
            )
        return result

    def _inspect(self, kind: str, reference: str, deadline: _Deadline):
        arguments = (
            ["image", "inspect", reference]
            if kind == "image"
            else ["inspect", reference]
        )
        result = self._docker(arguments, deadline, check=False)
        if result.returncode:
            return None
        try:
            values = json.loads(result.stdout)
            if (
                not isinstance(values, list)
                or len(values) != 1
                or not isinstance(values[0], dict)
            ):
                raise ValueError
            return values[0]
        except (ValueError, TypeError):
            raise SandboxError(
                "Sandbox resource identity could not be verified"
            ) from None

    def _base_image(self, deadline: _Deadline):
        platform = self._docker(
            ["version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"], deadline
        ).stdout.strip()
        digest = BASE_DIGESTS.get(platform)
        if digest is None:
            raise SandboxError("The Docker platform has no approved PHP sandbox image")
        reference = f"docker.io/library/php@{digest}"
        info = self._inspect("image", reference, deadline)
        if info is None:
            self._docker(["pull", reference], deadline)
            info = self._inspect("image", reference, deadline)
        if (
            not info
            or f"{info.get('Os')}/{info.get('Architecture')}" != platform
            or not _DIGEST.fullmatch(info.get("Id", ""))
        ):
            raise SandboxError("The pinned PHP sandbox image could not be verified")
        return digest

    @staticmethod
    def _owned(info, labels):
        recorded = info.get("Config", {}).get("Labels", {}) if info else {}
        return all(recorded.get(key) == value for key, value in labels.items())

    def _cleanup(self, container_name, image_tag, labels):
        deadline = _Deadline(15)
        failed = False
        for kind, reference in [("container", container_name), ("image", image_tag)]:
            try:
                info = self._inspect(kind, reference, deadline)
                if info is None:
                    continue
                resource_id = info.get("Id", "")
                valid = (
                    _CONTAINER_ID.fullmatch(resource_id)
                    if kind == "container"
                    else _DIGEST.fullmatch(resource_id)
                )
                if not valid or not self._owned(info, labels):
                    failed = True
                    continue
                arguments = (
                    ["rm", "--force", resource_id]
                    if kind == "container"
                    else ["image", "rm", resource_id]
                )
                self._docker(arguments, deadline)
            except SandboxError:
                failed = True
        if failed:
            raise SandboxError(
                "Sandbox cleanup could not verify or remove its owned resources"
            )

    def verify(
        self,
        files: dict[str, bytes],
        ini_content: str,
        manifest: SiteManifest,
        capabilities: list[str],
        phase: str,
        *,
        run_id: str,
    ) -> SandboxResult:
        _validate_inputs(files, ini_content, manifest, capabilities, phase, run_id)
        deadline = _Deadline(self.timeout_s)
        digest = self._base_image(deadline)
        token = uuid.uuid4().hex
        container_name = f"patchpilot-repair-{token}"
        image_tag = f"patchpilot-repair-sandbox:{token}"
        labels = {
            "patchpilot.sandbox.component": "github-repair",
            "patchpilot.sandbox.owner": self.owner,
            "patchpilot.sandbox.instance": token,
            "patchpilot.sandbox.run": hashlib.sha256(run_id.encode()).hexdigest(),
            "patchpilot.sandbox.base": digest,
        }
        parent = self.root / "var" / "repair-sandboxes"
        if (
            not parent.resolve().is_relative_to(self.root)
            or parent.resolve() == self.root
        ):
            raise SandboxError("Unsafe sandbox scratch root")
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise SandboxError("Sandbox scratch space is unavailable") from None
        try:
            with tempfile.TemporaryDirectory(prefix="job-", dir=parent) as directory:
                job = Path(directory)
                (job / ".owner").write_text(token)
                context = job / "context"
                (context / "app").mkdir(parents=True)
                trusted = context / "sandbox"
                trusted.mkdir()
                for name, content in files.items():
                    target = context / "app" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    target.chmod(0o644)
                (trusted / "php.ini").write_text(ini_content, encoding="utf-8")
                for name in ("router.php", "verify.php"):
                    (trusted / name).write_bytes((_ASSETS / name).read_bytes())
                metadata = {
                    "site_id": manifest.site_id,
                    "phase": phase,
                    "capabilities": capabilities,
                    "contact": manifest.contact,
                    "upload": manifest.upload,
                }
                (trusted / "manifest.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                (context / "Dockerfile").write_text(
                    f"FROM docker.io/library/php@{digest}\nCOPY app/ /app/\nCOPY sandbox/ /sandbox/\nWORKDIR /app\nUSER 65532:65532\n",
                    encoding="utf-8",
                )
                build = [
                    "build",
                    "--network",
                    "none",
                    "--pull=false",
                    "--quiet",
                    "--tag",
                    image_tag,
                ]
                for key, value in labels.items():
                    build += ["--label", f"{key}={value}"]
                self._docker([*build, str(context)], deadline)
                image = self._inspect("image", image_tag, deadline)
                if (
                    not image
                    or not self._owned(image, labels)
                    or not _DIGEST.fullmatch(image.get("Id", ""))
                ):
                    raise SandboxError("Sandbox image identity could not be verified")
                command = [
                    "run",
                    "--detach",
                    "--name",
                    container_name,
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "65532:65532",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "32",
                    "--memory",
                    "256m",
                    "--memory-swap",
                    "256m",
                    "--cpus",
                    "0.5",
                    "--ulimit",
                    "nofile=64:64",
                    "--tmpfs",
                    "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
                    "--ipc",
                    "none",
                    "--init",
                    "--log-driver",
                    "none",
                    "--stop-timeout",
                    "1",
                    "--env",
                    "PHP_INI_SCAN_DIR=",
                    "--entrypoint",
                    "php",
                ]
                for key, value in labels.items():
                    command += ["--label", f"{key}={value}"]
                command += [
                    image["Id"],
                    "-c",
                    "/sandbox/php.ini",
                    "-d",
                    f"disable_functions={_DISABLED_FUNCTIONS}",
                    "-d",
                    "open_basedir=/app:/tmp:/sandbox",
                    "-d",
                    "upload_tmp_dir=/tmp",
                    "-d",
                    "session.save_path=/tmp",
                    "-d",
                    "error_log=/tmp/php-errors.log",
                    "-S",
                    "127.0.0.1:8080",
                    "-t",
                    "/app",
                    "/sandbox/router.php",
                ]
                container_id = self._docker(command, deadline).stdout.strip()
                if not _CONTAINER_ID.fullmatch(container_id):
                    raise SandboxError(
                        "Sandbox container identity could not be verified"
                    )
                output = self._docker(
                    [
                        "exec",
                        "--user",
                        "65533:65533",
                        container_id,
                        "php",
                        "-n",
                        "/sandbox/verify.php",
                        str(max(1, math.floor(deadline.remaining() - 1))),
                    ],
                    deadline,
                ).stdout
                return self._result(output, manifest, capabilities, phase, digest)
        except SandboxError:
            raise
        except (OSError, ValueError, TypeError, KeyError):
            raise SandboxError("Sandbox verification could not complete") from None
        finally:
            self._cleanup(container_name, image_tag, labels)

    @staticmethod
    def _result(output: str, manifest: SiteManifest, capabilities, phase, digest):
        try:
            data = json.loads(output)
            runtime, identity, observations, timings = (
                data[key]
                for key in ("runtime", "identity", "observations", "durations_ms")
            )
            required = {
                "display_errors",
                "display_startup_errors",
                "log_errors",
                "expose_php",
            }
            if (
                set(runtime) != required | {"php_version"}
                or any(type(runtime[key]) is not bool for key in required)
                or runtime["php_version"] != PHP_VERSION
            ):
                raise ValueError
            if identity != {
                "sapi": "cli-server",
                "site_id": manifest.site_id,
                "phase": phase,
            }:
                raise ValueError
            if type(observations["banner_hidden"]) is not bool:
                raise ValueError
            if any(
                type(value) is not int or not 0 <= value <= 90000
                for value in timings.values()
            ):
                raise ValueError
            checks = []

            def add(check_id, label, passed, expected, observed, timing="runtime"):
                checks.append(
                    VerificationCheck(
                        check_id=check_id,
                        label=label,
                        phase=phase,
                        passed=passed,
                        expected=str(expected),
                        observed=str(observed),
                        duration_ms=timings[timing],
                    )
                )

            add(
                "runtime_version",
                "Pinned PHP version",
                True,
                PHP_VERSION,
                runtime["php_version"],
            )
            for key, expected in [
                ("display_errors", False),
                ("display_startup_errors", False),
                ("log_errors", True),
                ("expose_php", False),
            ]:
                add(
                    key,
                    key.replace("_", " ").capitalize(),
                    runtime[key] is expected,
                    "On" if expected else "Off",
                    "On" if runtime[key] else "Off",
                )
            add(
                "php_banner_hidden",
                "PHP version response banner hidden",
                observations["banner_hidden"],
                "No X-Powered-By header",
                "Absent" if observations["banner_hidden"] else "Present",
            )
            status = observations["homepage_status"]
            if type(status) is not int or not 0 <= status <= 599:
                raise ValueError
            add(
                "homepage_status",
                "Homepage responds successfully",
                status == 200,
                "HTTP 200",
                f"HTTP {status}" if status else "No complete response",
                "homepage",
            )
            if "contact" in capabilities:
                for check_id, valid, status_expected in [
                    ("contact_valid", True, 200),
                    ("contact_invalid", False, 422),
                ]:
                    item = observations[check_id]
                    if type(item["status"]) is not int or type(item["valid"]) not in {
                        bool,
                        type(None),
                    }:
                        raise ValueError
                    detail = item["errors_empty"] if valid else item["required_errors"]
                    if type(detail) is not bool:
                        raise ValueError
                    passed = (
                        item["status"] == status_expected
                        and item["valid"] is valid
                        and detail
                    )
                    add(
                        check_id,
                        "Contact accepts valid input"
                        if valid
                        else "Contact rejects invalid input",
                        passed,
                        f"HTTP {status_expected}; valid={str(valid).lower()}; expected field validation",
                        f"HTTP {item['status']}; valid={str(item['valid']).lower()}; field validation {'matches' if detail else 'does not match'}",
                        check_id,
                    )
            if "upload" in capabilities:
                item = observations["upload"]
                if (
                    type(item["status"]) is not int
                    or item["expected_bytes"] != 3145728
                    or type(item["sha256_matches"]) is not bool
                    or type(item["bytes_received"]) not in {int, type(None)}
                ):
                    raise ValueError
                expected_hash, received_hash = item["expected_sha256"], item["sha256"]
                if (
                    not isinstance(expected_hash, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                    or (
                        received_hash is not None
                        and (
                            not isinstance(received_hash, str)
                            or not re.fullmatch(r"[0-9a-f]{64}", received_hash)
                        )
                    )
                ):
                    raise ValueError
                if item["sha256_matches"] and expected_hash != received_hash:
                    raise ValueError
                size_ok = item["status"] == 200 and item["bytes_received"] == 3145728
                add(
                    "upload_size",
                    "Real 3 MiB upload byte count",
                    size_ok,
                    "3145728 bytes; HTTP 200",
                    f"{item['bytes_received']} bytes; HTTP {item['status']}"
                    if item["bytes_received"] is not None
                    else f"No valid byte count; HTTP {item['status']}",
                    "upload",
                )
                add(
                    "upload_sha256",
                    "Uploaded payload SHA-256",
                    item["status"] == 200 and item["sha256_matches"],
                    expected_hash,
                    received_hash or "Missing or invalid SHA-256",
                    "upload",
                )
            expected_ids = (
                REQUIRED_SECURITY_CHECKS
                | {"runtime_version"}
                | set().union(
                    *(BUSINESS_CHECKS[capability] for capability in capabilities)
                )
            )
            if {check.check_id for check in checks} != expected_ids:
                raise ValueError
            return SandboxResult(tuple(checks), runtime, digest)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise SandboxError(
                "Sandbox verifier returned incomplete or invalid observations"
            ) from None
