"""Core/runtime contract tests with an in-memory Docker and HTTP boundary."""

import hashlib
import http.client
import json
import subprocess
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from patchpilot.core.domain import checks_complete
from patchpilot.core.policy import ConfigurationProfile, RepairPlan, ValidatedPlan
from patchpilot.runtime.bridge import DockerRuntime, HttpVerifier

DIGEST = "sha256:" + "a" * 64
ORIGINAL_IMAGE = "sha256:" + "b" * 64
CANDIDATE_IMAGE = "sha256:" + "c" * 64


class MemoryRuntime(DockerRuntime):
    """Model daemon state and actual serving responses without launching Docker."""

    def __init__(self):
        super().__init__()
        self.containers = {}
        self.images = {}
        self.commands = []
        self.tamper = {}
        self.fail_rename = False
        self._patched_digest = DIGEST

    def seed(self, site_id="pantry-a"):
        entry = self.manifest[site_id]
        self.containers[f"patchpilot-{site_id}"] = {
            "Id": f"container-{site_id}",
            "Image": ORIGINAL_IMAGE,
            "Config": {
                "Labels": self._labels(site_id, "fixture"),
                "Env": [
                    f"SITE_ID={site_id}",
                    f"ORG_NAME={entry['organization']}",
                    f"DEPLOYMENT_ID=baseline-{site_id}",
                ],
            },
            "State": {"Running": True},
            "HostConfig": {
                "PortBindings": {
                    "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(entry["port"])}]
                }
            },
            "NetworkSettings": {
                "Ports": {
                    "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(entry["port"])}]
                }
            },
            "php_version": "8.3.35",
            "progress": True,
            "config_hash": "original-config",
        }
        return self.inspect(self.sites[site_id], timeout_s=5)

    def _docker(self, args, deadline, *, check=True):
        self.commands.append(args)
        output, code = "", 0
        if args[0] == "inspect":
            item = self.containers.get(args[1])
            output, code = (json.dumps([item]), 0) if item else ("", 1)
        elif args[:2] == ["image", "inspect"]:
            image = self.images.get(args[2])
            output, code = (json.dumps([image]), 0) if image else ("", 1)
        elif args[0] == "build":
            labels = dict(
                args[i + 1].split("=", 1)
                for i, value in enumerate(args)
                if value == "--label"
            )
            self.images[args[args.index("-t") + 1]] = {
                "Id": CANDIDATE_IMAGE,
                "Config": {"Labels": labels},
            }
        elif args[0] == "run":
            name = args[args.index("--name") + 1]
            env = [args[i + 1] for i, value in enumerate(args) if value == "-e"]
            labels = dict(
                args[i + 1].split("=", 1)
                for i, value in enumerate(args)
                if value == "--label"
            )
            port = args[args.index("-p") + 1].split(":")[1]
            assigned_port = port or str(25000 + len(self.containers))
            self.containers[name] = {
                "Id": "container-" + name,
                "Image": args[-1],
                "Config": {"Labels": labels, "Env": env},
                "State": {"Running": True},
                "HostConfig": {
                    "PortBindings": {
                        "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]
                    }
                },
                "NetworkSettings": {
                    "Ports": {
                        "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": assigned_port}]
                    }
                },
                "php_version": "8.3.36",
                "progress": False,
                "config_hash": "repaired-config",
            }
            output = self.containers[name]["Id"]
        elif args[0] == "stop":
            self.containers[args[-1]]["State"]["Running"] = False
        elif args[0] == "rename":
            if self.fail_rename:
                raise RuntimeError("rename failed")
            self.containers[args[2]] = self.containers.pop(args[1])
        elif args[0] == "start":
            self.containers[args[-1]]["State"]["Running"] = True
        elif args[0] == "rm":
            key = next(
                (
                    name
                    for name, item in self.containers.items()
                    if item["Id"] == args[-1]
                ),
                args[-1],
            )
            self.containers.pop(key, None)
        elif args[:2] == ["image", "rm"]:
            self.images.pop(args[-1], None)
        else:
            raise AssertionError(f"Unexpected command: {args}")
        if check and code:
            raise RuntimeError("Missing container")
        return subprocess.CompletedProcess(args, code, output, "")

    def _hashes(self, info, deadline):
        return {
            "application_hash": hashlib.sha256(b"same-app").hexdigest(),
            "configuration_hash": hashlib.sha256(
                info["config_hash"].encode()
            ).hexdigest(),
        }

    def _request(
        self, endpoint, path, deadline, *, method="GET", body=None, headers=None
    ):
        port = endpoint.rsplit(":", 1)[-1]
        item = next(
            c
            for c in self.containers.values()
            if c["State"]["Running"]
            and c["NetworkSettings"]["Ports"]["80/tcp"][0]["HostPort"] == port
        )
        env = dict(value.split("=", 1) for value in item["Config"]["Env"])
        if path == "/runtime.php":
            data = {
                "status": "ok",
                "site_id": env["SITE_ID"],
                "deployment_id": env["DEPLOYMENT_ID"],
                "php_version": item["php_version"],
                "php_sapi": "apache2handler",
                "session_upload_progress_enabled": item["progress"],
                "upload_max_filesize": "8M",
                "post_max_size": "10M",
            }
            data.update(self.tamper)
            return 200, json.dumps(data).encode()
        if path == "/":
            return 200, f"{env['ORG_NAME']} Contact Us".encode()
        if path == "/contact.php":
            valid = b"not-an-email" not in body
            return (200 if valid else 422), json.dumps(
                {
                    "valid": valid,
                    "errors": {}
                    if valid
                    else {
                        "name": "required",
                        "email": "invalid",
                        "message": "required",
                    },
                }
            ).encode()
        if path == "/upload.php":
            payload = HttpVerifier.upload_payload()
            assert payload in body
            return 200, json.dumps(
                {
                    "bytes_received": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    **self.tamper,
                }
            ).encode()
        raise AssertionError(path)


def plan():
    return ValidatedPlan(
        RepairPlan("php83_patched", "preserve_basic"),
        DIGEST,
        ConfigurationProfile("preserve_basic", "2M", "8M"),
    )


def test_manifest_preserves_actual_organization_and_template():
    runtime = DockerRuntime()
    assert runtime.sites["pantry-a"].template_revision == "basic-v1"
    assert runtime.manifest["pantry-a"]["organization"] == "Midwest Food Pantry"
    assert runtime.sites["clinic-a"].capabilities == frozenset(
        {"homepage", "contact", "upload"}
    )


def test_registered_id_cannot_be_redirected_to_another_loopback_site():
    runtime = MemoryRuntime()
    with pytest.raises(ValueError, match="registered"):
        runtime.inspect(
            replace(runtime.sites["pantry-a"], base_url="http://127.0.0.1:9999"),
            timeout_s=5,
        )
    assert not runtime.commands


def test_stage_activate_and_restore_preserve_actual_immutable_identity():
    runtime = MemoryRuntime()
    original = runtime.seed()
    site = runtime.sites["pantry-a"]
    candidate = runtime.stage(site, plan(), "run-1", 1, timeout_s=5)
    assert candidate.snapshot.application_hash == original.application_hash
    activated = runtime.activate(site, candidate, original, timeout_s=5)
    assert activated == replace(candidate.snapshot, base_url=site.base_url)
    assert runtime.containers["patchpilot-pantry-a"]["Image"] == CANDIDATE_IMAGE
    assert runtime.restore(site, original, timeout_s=5) == original
    runtime.cleanup(site, "run-1", 1, timeout_s=5)
    assert not any("cand" in name for name in runtime.containers)


def test_staging_uses_engine_assigned_port_and_observed_network_binding():
    runtime = MemoryRuntime()
    runtime.seed()
    candidate = runtime.stage(
        runtime.sites["pantry-a"], plan(), "assigned-port", 1, timeout_s=5
    )
    info = runtime.containers[candidate.handle]
    assert info["HostConfig"]["PortBindings"]["80/tcp"][0]["HostPort"] == ""
    assert candidate.snapshot.base_url == "http://127.0.0.1:25001"
    assert checks_complete(
        runtime.sites["pantry-a"],
        HttpVerifier(runtime).check(
            runtime.sites["pantry-a"], candidate.snapshot, "STAGING", timeout_s=5
        ),
    )


def test_first_registry_resolution_preserves_verified_reference_for_offline_reuse(
    monkeypatch,
):
    runtime = DockerRuntime()
    images = {}
    calls = []
    info = {
        "Id": DIGEST,
        "Os": "linux",
        "Architecture": "arm64",
        "RepoDigests": ["php@" + DIGEST],
        "Descriptor": {
            "digest": DIGEST,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
        },
    }

    def docker(args, deadline, *, check=True):
        calls.append(args)
        if args[0] == "version":
            return subprocess.CompletedProcess(args, 0, "linux/arm64", "")
        if args[:2] == ["image", "inspect"]:
            value = images.get(args[-1])
            return subprocess.CompletedProcess(
                args, 0 if value else 1, json.dumps([value]) if value else "", ""
            )
        if args[0] == "manifest":
            descriptor = {
                **info["Descriptor"],
                "platform": {"os": "linux", "architecture": "arm64"},
            }
            return subprocess.CompletedProcess(
                args, 0, json.dumps([{"Descriptor": descriptor}]), ""
            )
        if args[0] == "pull":
            images[args[1]] = info
        elif args[0] == "tag":
            images[args[2]] = images[args[1]]
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(runtime, "_docker", docker)
    assert runtime.resolve_patched_digest(timeout_s=5) == DIGEST
    assert runtime.resolve_patched_digest(timeout_s=5) == DIGEST
    assert sum(command[0] == "manifest" for command in calls) == 1
    assert sum(command[0] == "pull" for command in calls) == 1


def test_restore_does_not_delete_original_when_activation_rename_failed():
    runtime = MemoryRuntime()
    original = runtime.seed()
    site = runtime.sites["pantry-a"]
    candidate = runtime.stage(site, plan(), "run-2", 1, timeout_s=5)
    runtime.fail_rename = True
    with pytest.raises(RuntimeError):
        runtime.activate(site, candidate, original, timeout_s=5)
    assert runtime.restore(site, original, timeout_s=5) == original
    assert "patchpilot-pantry-a" in runtime.containers


def test_restore_refuses_to_remove_replacement_without_retained_original():
    runtime = MemoryRuntime()
    original = runtime.seed()
    runtime.containers["patchpilot-pantry-a"]["Image"] = CANDIDATE_IMAGE
    with pytest.raises(RuntimeError, match="retained"):
        runtime.restore(runtime.sites["pantry-a"], original, timeout_s=5)
    assert "patchpilot-pantry-a" in runtime.containers
    assert not any(command[0] == "rm" for command in runtime.commands)


@pytest.mark.parametrize("site_id,count", [("pantry-a", 7), ("clinic-a", 9)])
def test_verifier_returns_complete_actual_phase_evidence(site_id, count):
    runtime = MemoryRuntime()
    snapshot = runtime.seed(site_id)
    checks = HttpVerifier(runtime).check(
        runtime.sites[site_id], snapshot, "BASELINE", timeout_s=5
    )
    assert len(checks) == count
    assert checks_complete(runtime.sites[site_id], checks)
    assert all(check.phase == "BASELINE" for check in checks)


@pytest.mark.parametrize(
    "tamper,failed",
    [
        ({"php_sapi": "cli"}, "sapi"),
        ({"site_id": "other-site"}, "deployment_identity"),
        ({"deployment_id": "other-deployment"}, "deployment_identity"),
        ({"php_version": "8.3.350"}, "runtime_version"),
        ({"session_upload_progress_enabled": "false"}, "upload_progress"),
        ({"status": "bad"}, "deployment_identity"),
    ],
)
def test_verifier_rejects_malformed_or_changed_runtime(tamper, failed):
    runtime = MemoryRuntime()
    snapshot = runtime.seed()
    runtime.tamper = tamper
    checks = HttpVerifier(runtime).check(
        runtime.sites["pantry-a"], snapshot, "LIVE", timeout_s=5
    )
    assert next(check for check in checks if check.check_id == failed).passed is False


@pytest.mark.parametrize(
    "tamper,failed",
    [({"bytes_received": 1024}, "upload_size"), ({"sha256": "bad"}, "upload_hash")],
)
def test_verifier_requires_upload_size_and_hash(tamper, failed):
    runtime = MemoryRuntime()
    snapshot = runtime.seed("clinic-a")
    runtime.tamper = tamper
    checks = HttpVerifier(runtime).check(
        runtime.sites["clinic-a"], snapshot, "BASELINE", timeout_s=5
    )
    assert next(check for check in checks if check.check_id == failed).passed is False


def test_cleanup_refuses_a_container_with_foreign_ownership():
    runtime = MemoryRuntime()
    runtime.seed()
    site = runtime.sites["pantry-a"]
    candidate = runtime.stage(site, plan(), "run-foreign", 1, timeout_s=5)
    runtime.containers[candidate.handle]["Config"]["Labels"]["patchpilot.project"] = (
        "other-project"
    )
    with pytest.raises(RuntimeError, match="ownership"):
        runtime.cleanup(site, "run-foreign", 1, timeout_s=5)
    assert candidate.handle in runtime.containers


def test_command_timeout_is_finite_and_expired_budget_never_starts_a_command(
    monkeypatch,
):
    from patchpilot.runtime.bridge import Deadline

    calls = []

    def run(args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", run)
    DockerRuntime()._docker(["version"], Deadline(1))
    assert 0 < calls[0]["timeout"] <= 1
    with pytest.raises(ValueError):
        Deadline(float("inf"))


def test_http_deadline_interrupts_a_slow_connection_close_response():
    from patchpilot.runtime.bridge import Deadline

    class SlowResponse(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowResponse)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises((TimeoutError, OSError, http.client.HTTPException)):
            DockerRuntime()._request(
                f"http://127.0.0.1:{server.server_port}", "/", Deadline(0.15)
            )
        assert time.monotonic() - started < 0.8
    finally:
        server.shutdown()
        server.server_close()


def test_resolved_official_platform_image_is_reused_without_registry_requests(
    monkeypatch,
):
    runtime = DockerRuntime()
    calls = []

    def docker(args, deadline, *, check=True):
        calls.append(args)
        if args[0] == "version":
            return subprocess.CompletedProcess(args, 0, "linux/arm64", "")
        if args[:2] == ["image", "inspect"]:
            info = {
                "Id": DIGEST,
                "Os": "linux",
                "Architecture": "arm64",
                "RepoDigests": ["php@" + DIGEST],
                "Descriptor": {
                    "digest": DIGEST,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
            }
            return subprocess.CompletedProcess(args, 0, json.dumps([info]), "")
        raise AssertionError(
            "Verified local official image must not contact the registry"
        )

    monkeypatch.setattr(runtime, "_docker", docker)
    assert runtime.resolve_patched_digest(timeout_s=5) == DIGEST
    assert not any(command[0] in {"manifest", "pull"} for command in calls)
