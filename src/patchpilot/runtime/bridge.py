"""Bounded Docker/HTTP adapters for the repair engine's normalized contracts.

Only registered fixture endpoints and workspace-owned Docker resources are used.
HTTP observations establish the serving runtime; copied container files establish
content identity, including when a retained original is stopped.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import re
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from patchpilot.core.domain import (
    DeploymentSnapshot,
    Site,
    checks_complete,
)
from patchpilot.core.policy import ConfigurationProfile, ValidatedPlan
from patchpilot.core.ports import Candidate
from patchpilot.runtime.deadline import Deadline
from patchpilot.runtime.http_verifier import HttpVerifier

logger = logging.getLogger(__name__)
PATCHED_IMAGE = "docker.io/library/php:8.3.36-apache"
BASELINE_IMAGE = "docker.io/library/php:8.3.35-apache"
PROFILES = {
    "preserve_basic": (
        "pantry-repaired.ini",
        ConfigurationProfile("preserve_basic", "2M", "8M"),
    ),
    "preserve_uploads": (
        "clinic-upload-repaired.ini",
        ConfigurationProfile("preserve_uploads", "8M", "10M"),
    ),
}
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


class DockerRuntime:
    """Real, synchronous implementation of ``core.ports.Runtime``."""

    def __init__(self, workspace_root: Path | None = None):
        self.workspace_root = (
            workspace_root or Path(__file__).resolve().parents[3]
        ).resolve()
        self.project_id = hashlib.sha256(str(self.workspace_root).encode()).hexdigest()[
            :16
        ]
        document = json.loads(
            (self.workspace_root / "config" / "fleet.json").read_text()
        )
        self.manifest: dict[str, dict[str, Any]] = {}
        self.sites: dict[str, Site] = {}
        for entry in document:
            site_id = entry["id"]
            port = entry["port"]
            if (
                not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", site_id)
                or site_id in self.sites
                or type(port) is not int
                or not 1 <= port <= 65535
                or entry["endpoint"] != f"http://127.0.0.1:{port}"
                or not entry.get("organization")
                or not {"homepage", "contact"} <= set(entry["requiredCapabilities"])
                or not set(entry["requiredCapabilities"])
                <= {"homepage", "contact", "upload"}
                or entry["originalImage"] != "php:8.3.35-apache"
                or entry["originalConfigProfile"]
                not in {"pantry-default", "clinic-upload-original"}
            ):
                raise ValueError("Invalid registered fixture manifest")
            self.manifest[site_id] = dict(entry)
            self.sites[site_id] = Site(
                site_id,
                entry["endpoint"],
                entry["templateRevision"],
                frozenset(entry["requiredCapabilities"]),
            )
        if (
            len(self.sites) != 4
            or len({site.base_url for site in self.sites.values()}) != 4
        ):
            raise ValueError("Exactly four distinct registered fixtures are required")
        self._patched_digest: str | None = None

    def _site(self, site: Site) -> dict[str, Any]:
        if self.sites.get(site.site_id) != site:
            raise ValueError("Site does not match the registered fixture")
        return self.manifest[site.site_id]

    def _docker(
        self, args: list[str], deadline: Deadline, *, check: bool = True
    ) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                ["docker", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=deadline.remaining(),
            )
        except FileNotFoundError as error:
            raise RuntimeError("Docker CLI is unavailable") from error
        if check and result.returncode:
            logger.error("Docker %s failed: %s", args[0], result.stderr[-2000:])
            raise RuntimeError(
                f"Docker {args[0]} failed; inspect local runtime diagnostics"
            )
        return result

    def _labels(
        self,
        site_id: str,
        role: str,
        run_id: str | None = None,
        attempt: int | None = None,
    ) -> dict[str, str]:
        labels = {
            "app": f"patchpilot-{role}",
            "patchpilot.managed_by": "patchpilot",
            "patchpilot.project": self.project_id,
            "patchpilot.site_id": site_id,
        }
        if run_id is not None:
            labels["patchpilot.run_id"] = run_id
        if attempt is not None:
            labels["patchpilot.attempt"] = str(attempt)
        return labels

    def _owned(
        self,
        info: dict[str, Any],
        site_id: str,
        *,
        role: str | None = None,
        run_id: str | None = None,
        attempt: int | None = None,
    ) -> None:
        labels = info.get("Config", {}).get("Labels") or {}
        expected = self._labels(site_id, role or "fixture", run_id, attempt)
        if role is None:
            expected.pop("app")
        if (
            not info.get("Id")
            or any(labels.get(key) != value for key, value in expected.items())
            or labels.get("app")
            not in {"patchpilot-fixture", "patchpilot-live", "patchpilot-candidate"}
        ):
            raise RuntimeError("Docker resource ownership does not match this project")

    def _container(self, name: str, deadline: Deadline) -> dict[str, Any] | None:
        result = self._docker(["inspect", name], deadline, check=False)
        if result.returncode:
            if result.stderr and not any(
                text in result.stderr.lower()
                for text in ("no such object", "no such container")
            ):
                raise RuntimeError("Docker container inspection failed")
            return None
        value = json.loads(result.stdout)
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise RuntimeError("Docker returned malformed container inspection")
        return value[0]

    def _image(self, reference: str, deadline: Deadline) -> dict[str, Any] | None:
        result = self._docker(["image", "inspect", reference], deadline, check=False)
        if result.returncode:
            if (
                result.stderr
                and "no such image" not in result.stderr.lower()
                and "no such object" not in result.stderr.lower()
            ):
                raise RuntimeError("Docker image inspection failed")
            return None
        value = json.loads(result.stdout)
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not _DIGEST.fullmatch(value[0].get("Id", ""))
        ):
            raise RuntimeError("Docker did not return an immutable image identity")
        return value[0]

    @staticmethod
    def _env(info: dict[str, Any]) -> dict[str, str]:
        return dict(
            item.split("=", 1)
            for item in info.get("Config", {}).get("Env", [])
            if "=" in item
        )

    def _request(
        self,
        endpoint: str,
        path: str,
        deadline: Deadline,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Only registered loopback HTTP endpoints are supported")
        connection = http.client.HTTPConnection(
            parsed.hostname, parsed.port or 80, timeout=deadline.remaining()
        )
        connection.connect()
        request_socket = connection.sock

        def interrupt() -> None:
            if request_socket is not None:
                try:
                    request_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = threading.Timer(deadline.remaining(), interrupt)
        timer.daemon = True
        timer.start()
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            chunks: list[bytes] = []
            length = 0
            while True:
                if request_socket is not None:
                    request_socket.settimeout(deadline.remaining())
                else:
                    deadline.remaining()
                chunk = response.read1(65536)
                if not chunk:
                    break
                length += len(chunk)
                if length > 1024 * 1024:
                    raise ValueError(
                        "Fixture response exceeded the 1 MiB response limit"
                    )
                chunks.append(chunk)
            deadline.remaining()
            return response.status, b"".join(chunks)
        finally:
            timer.cancel()
            connection.close()

    def _probe(self, endpoint: str, deadline: Deadline) -> dict[str, Any]:
        status, body = self._request(endpoint, "/runtime.php", deadline)
        value = json.loads(body)
        if status != 200 or not isinstance(value, dict):
            raise RuntimeError("Serving runtime probe did not return HTTP 200 JSON")
        return value

    def _hashes(self, info: dict[str, Any], deadline: Deadline) -> dict[str, str]:
        hashes = {}
        with tempfile.TemporaryDirectory(prefix="patchpilot-content-") as directory:
            for key, source in (
                ("application_hash", "/var/www/html"),
                ("configuration_hash", "/usr/local/etc/php"),
            ):
                target = Path(directory) / key
                self._docker(["cp", f"{info['Id']}:{source}", str(target)], deadline)
                digest = hashlib.sha256()
                files = sorted(target.rglob("*"))
                total = 0
                if len(files) > 1000:
                    raise RuntimeError(
                        "Fixture content exceeded the registered file limit"
                    )
                for path in files:
                    deadline.remaining()
                    if path.is_symlink():
                        raise RuntimeError(
                            "Symbolic links are outside the fixture content contract"
                        )
                    if not path.is_file():
                        continue
                    total += path.stat().st_size
                    if total > 16 * 1024 * 1024:
                        raise RuntimeError(
                            "Fixture content exceeded the registered size limit"
                        )
                    digest.update(path.relative_to(target).as_posix().encode() + b"\0")
                    digest.update(hashlib.sha256(path.read_bytes()).digest())
                hashes[key] = digest.hexdigest()
        return hashes

    def _snapshot(
        self,
        site: Site,
        info: dict[str, Any],
        endpoint: str,
        deadline: Deadline,
        *,
        base_digest: str | None = None,
    ) -> DeploymentSnapshot:
        self._owned(info, site.site_id)
        if self._published_endpoint(info) != endpoint:
            raise RuntimeError("Container does not own the expected loopback endpoint")
        probe = self._probe(endpoint, deadline)
        env = self._env(info)
        if (
            probe.get("status") != "ok"
            or probe.get("site_id") != site.site_id
            or not isinstance(probe.get("deployment_id"), str)
            or not probe["deployment_id"]
            or probe["deployment_id"] != env.get("DEPLOYMENT_ID")
            or env.get("SITE_ID") != site.site_id
            or type(probe.get("session_upload_progress_enabled")) is not bool
            or not isinstance(probe.get("php_version"), str)
            or not re.fullmatch(r"\d+\.\d+\.\d+", probe["php_version"])
            or not isinstance(probe.get("php_sapi"), str)
            or not _DIGEST.fullmatch(info.get("Image", ""))
        ):
            raise RuntimeError(
                "Serving runtime identity or types do not match the owned container"
            )
        hashes = self._hashes(info, deadline)
        return DeploymentSnapshot(
            site.site_id,
            probe["deployment_id"],
            info["Image"],
            hashes["application_hash"],
            hashes["configuration_hash"],
            probe["php_version"],
            probe["php_sapi"],
            probe["session_upload_progress_enabled"],
            base_digest,
            endpoint,
        )

    @staticmethod
    def _published_endpoint(info: dict[str, Any]) -> str:
        bindings = info.get("NetworkSettings", {}).get("Ports", {}).get("80/tcp") or []
        if (
            len(bindings) != 1
            or bindings[0].get("HostIp") != "127.0.0.1"
            or not isinstance(bindings[0].get("HostPort"), str)
            or not bindings[0]["HostPort"].isdigit()
            or not 1 <= int(bindings[0]["HostPort"]) <= 65535
        ):
            raise RuntimeError("Container has no unique published loopback HTTP port")
        return f"http://127.0.0.1:{int(bindings[0]['HostPort'])}"

    def _inspect(self, site: Site, deadline: Deadline) -> DeploymentSnapshot:
        self._site(site)
        info = self._container(f"patchpilot-{site.site_id}", deadline)
        if info is None or not info.get("State", {}).get("Running"):
            raise RuntimeError(
                "Registered fixture is not running; prepare the fleet first"
            )
        labels = info.get("Config", {}).get("Labels") or {}
        return self._snapshot(
            site,
            info,
            site.base_url,
            deadline,
            base_digest=labels.get("patchpilot.base_digest"),
        )

    def inspect(self, site: Site, *, timeout_s: float) -> DeploymentSnapshot:
        return self._inspect(site, Deadline(timeout_s))

    def _resolve_image(self, reference: str, deadline: Deadline) -> str:
        platform = self._docker(
            ["version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"], deadline
        ).stdout.strip()
        os_name, architecture = platform.split("/", 1)
        # Docker's trusted local content store retains the official repository
        # provenance and the exact platform descriptor. Recheck both identities
        # on every reuse rather than repeatedly consuming registry pull quota.
        local = self._docker(
            ["image", "inspect", f"--platform={platform}", reference],
            deadline,
            check=False,
        )
        if local.returncode == 0:
            values = json.loads(local.stdout)
            info = values[0] if isinstance(values, list) and len(values) == 1 else {}
            descriptor = info.get("Descriptor", {})
            digest = descriptor.get("digest", "")
            repositories = info.get("RepoDigests") or []
            if (
                info.get("Os") == os_name
                and info.get("Architecture") == architecture
                and _DIGEST.fullmatch(digest)
                and descriptor.get("mediaType")
                in {
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                }
                and any(
                    repository.startswith(
                        ("php@sha256:", "docker.io/library/php@sha256:")
                    )
                    for repository in repositories
                )
            ):
                pinned = self._image(f"docker.io/library/php@{digest}", deadline)
                if (
                    pinned is not None
                    and pinned["Id"] == info.get("Id")
                    and pinned.get("Os") == os_name
                    and pinned.get("Architecture") == architecture
                ):
                    return digest
        document = json.loads(
            self._docker(
                ["manifest", "inspect", "--verbose", reference], deadline
            ).stdout
        )
        records = document if isinstance(document, list) else [document]
        descriptors = [record.get("Descriptor", {}) for record in records]
        matches = [
            item
            for item in descriptors
            if item.get("platform", {}).get("os") == os_name
            and item.get("platform", {}).get("architecture") == architecture
        ]
        if len(matches) != 1 or not _DIGEST.fullmatch(matches[0].get("digest", "")):
            raise RuntimeError(
                "Official PHP image has no unique manifest for the Docker engine platform"
            )
        digest = matches[0]["digest"]
        pinned = f"docker.io/library/php@{digest}"
        self._docker(["pull", pinned], deadline)
        pulled = self._image(pinned, deadline)
        if (
            pulled is None
            or pulled.get("Os") != os_name
            or pulled.get("Architecture") != architecture
        ):
            raise RuntimeError("Pulled PHP platform image cannot be inspected")
        # Keep the verified official tag-to-platform association available in the
        # local store even on a clean engine that only pulled the pinned digest.
        self._docker(["tag", pinned, reference], deadline)
        return digest

    def resolve_patched_digest(self, *, timeout_s: float = 120) -> str:
        self._patched_digest = self._resolve_image(PATCHED_IMAGE, Deadline(timeout_s))
        return self._patched_digest

    @staticmethod
    def _key(site: Site, run_id: str, attempt: int) -> tuple[str, str]:
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", run_id)
            or type(attempt) is not int
            or attempt not in (1, 2)
        ):
            raise ValueError("Invalid staging run or attempt")
        token = hashlib.sha256(
            f"{site.site_id}/{run_id}/{attempt}".encode()
        ).hexdigest()[:24]
        return f"patchpilot-cand-{site.site_id}-{run_id}-{attempt}", token

    def _build(
        self,
        site: Site,
        tag: str,
        digest: str,
        profile: str,
        labels: dict[str, str],
        deadline: Deadline,
    ) -> str:
        args = [
            "build",
            "-t",
            tag,
            "--build-arg",
            f"BASE_IMAGE=docker.io/library/php@{digest}",
            "--build-arg",
            f"CONFIG_PROFILE={profile}",
        ]
        for key, value in {**labels, "patchpilot.base_digest": digest}.items():
            args += ["--label", f"{key}={value}"]
        self._docker([*args, str(self.workspace_root / "fixtures")], deadline)
        image = self._image(tag, deadline)
        if image is None:
            raise RuntimeError("Built fixture image cannot be inspected")
        return image["Id"]

    def _launch(
        self,
        site: Site,
        name: str,
        image_id: str,
        port: int | None,
        deployment_id: str,
        labels: dict[str, str],
        deadline: Deadline,
    ) -> None:
        entry = self._site(site)
        published_port = "" if port is None else str(port)
        args = ["run", "-d", "--name", name, "-p", f"127.0.0.1:{published_port}:80"]
        env = {
            "SITE_ID": site.site_id,
            "ORG_NAME": entry["organization"],
            "ORG_TAGLINE": entry.get("tagline", ""),
            "CAPABILITIES": ",".join(sorted(site.capabilities)),
            "DEPLOYMENT_ID": deployment_id,
        }
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        for key, value in labels.items():
            args += ["--label", f"{key}={value}"]
        self._docker([*args, image_id], deadline)

    def _wait(self, endpoint: str, deployment_id: str, deadline: Deadline) -> None:
        while True:
            deadline.remaining()
            try:
                probe = self._probe(endpoint, deadline)
                if (
                    probe.get("status") == "ok"
                    and probe.get("deployment_id") == deployment_id
                ):
                    return
            except (OSError, ValueError, RuntimeError, http.client.HTTPException):
                pass
            time.sleep(min(0.2, deadline.remaining()))

    def stage(
        self,
        site: Site,
        plan: ValidatedPlan,
        run_id: str,
        attempt: int,
        *,
        timeout_s: float,
    ) -> Candidate:
        self._site(site)
        deadline = Deadline(timeout_s)
        profile = PROFILES.get(plan.profile.profile_id)
        if (
            profile is None
            or profile[1] != plan.profile
            or plan.plan.target_image_alias != "php83_patched"
            or plan.plan.config_profile_id != plan.profile.profile_id
            or not _DIGEST.fullmatch(plan.image_digest)
            or plan.image_digest != self._patched_digest
        ):
            raise ValueError(
                "Plan is outside the resolved image and configuration allowlist"
            )
        name, token = self._key(site, run_id, attempt)
        if self._container(name, deadline) is not None:
            raise RuntimeError(
                "Staging attempt already exists; reconcile it before retrying"
            )
        labels = self._labels(site.site_id, "candidate", run_id, attempt)
        tag = f"patchpilot-candidate:{self.project_id}-{token}"
        image_id = self._build(
            site, tag, plan.image_digest, profile[0], labels, deadline
        )
        deployment_id = f"{site.site_id}-cand-{run_id}-{attempt}"
        self._launch(
            site,
            name,
            image_id,
            None,
            deployment_id,
            {**labels, "patchpilot.base_digest": plan.image_digest},
            deadline,
        )
        info = self._container(name, deadline)
        if info is None:
            raise RuntimeError("Staged container disappeared")
        endpoint = self._published_endpoint(info)
        self._wait(endpoint, deployment_id, deadline)
        snapshot = self._snapshot(
            site, info, endpoint, deadline, base_digest=plan.image_digest
        )
        return Candidate(name, snapshot)

    def activate(
        self,
        site: Site,
        candidate: Candidate,
        original: DeploymentSnapshot,
        *,
        timeout_s: float,
    ) -> DeploymentSnapshot:
        self._site(site)
        deadline = Deadline(timeout_s)
        staged = self._container(candidate.handle, deadline)
        if staged is None:
            raise RuntimeError("Staged candidate is unavailable")
        self._owned(staged, site.site_id, role="candidate")
        labels = staged["Config"]["Labels"]
        run_id, attempt = labels["patchpilot.run_id"], int(labels["patchpilot.attempt"])
        if candidate.handle != self._key(site, run_id, attempt)[0]:
            raise RuntimeError("Candidate handle does not match its owned run")
        observed = self._snapshot(
            site,
            staged,
            candidate.snapshot.base_url,
            deadline,
            base_digest=labels.get("patchpilot.base_digest"),
        )
        if (
            observed != candidate.snapshot
            or observed.base_image_digest != self._patched_digest
        ):
            raise RuntimeError("Staged candidate identity changed before activation")
        if self._inspect(site, deadline) != original:
            raise RuntimeError("Original identity changed before activation")
        live_name, retained_name = (
            f"patchpilot-{site.site_id}",
            f"patchpilot-orig-retained-{site.site_id}",
        )
        retained = self._container(retained_name, deadline)
        if retained is not None:
            self._owned(retained, site.site_id)
            self._docker(["rm", "-f", retained["Id"]], deadline)
        self._docker(["stop", live_name], deadline)
        self._docker(["rename", live_name, retained_name], deadline)
        live_labels = {
            **self._labels(site.site_id, "live", run_id, attempt),
            "patchpilot.base_digest": observed.base_image_digest,
        }
        self._launch(
            site,
            live_name,
            observed.image_id,
            self.manifest[site.site_id]["port"],
            observed.deployment_id,
            live_labels,
            deadline,
        )
        self._wait(site.base_url, observed.deployment_id, deadline)
        return self._inspect(site, deadline)

    def _matches_original(
        self, info: dict[str, Any], original: DeploymentSnapshot, deadline: Deadline
    ) -> bool:
        self._owned(info, original.site_id)
        env = self._env(info)
        if (
            info.get("Image") != original.image_id
            or env.get("DEPLOYMENT_ID") != original.deployment_id
            or env.get("SITE_ID") != original.site_id
        ):
            return False
        hashes = self._hashes(info, deadline)
        return (
            hashes["application_hash"] == original.application_hash
            and hashes["configuration_hash"] == original.configuration_hash
        )

    def restore(
        self, site: Site, original: DeploymentSnapshot, *, timeout_s: float
    ) -> DeploymentSnapshot:
        self._site(site)
        if original.site_id != site.site_id or original.base_url != site.base_url:
            raise ValueError("Original is outside the registered restoration scope")
        deadline = Deadline(timeout_s)
        live_name, retained_name = (
            f"patchpilot-{site.site_id}",
            f"patchpilot-orig-retained-{site.site_id}",
        )
        active = self._container(live_name, deadline)
        if active is not None and self._matches_original(active, original, deadline):
            if not active.get("State", {}).get("Running"):
                self._docker(["start", live_name], deadline)
            self._wait(site.base_url, original.deployment_id, deadline)
            return self._inspect(site, deadline)
        retained = self._container(retained_name, deadline)
        if retained is None or not self._matches_original(retained, original, deadline):
            raise RuntimeError(
                "Verified retained original is unavailable; replacement was preserved"
            )
        if active is not None:
            self._owned(active, site.site_id, role="live")
            self._docker(["rm", "-f", active["Id"]], deadline)
        self._docker(["rename", retained_name, live_name], deadline)
        self._docker(["start", live_name], deadline)
        self._wait(site.base_url, original.deployment_id, deadline)
        restored = self._inspect(site, deadline)
        if restored != original:
            raise RuntimeError("Restored runtime differs from the retained original")
        return restored

    def cleanup(
        self, site: Site, run_id: str, attempt: int, *, timeout_s: float
    ) -> None:
        self._site(site)
        deadline = Deadline(timeout_s)
        name, token = self._key(site, run_id, attempt)
        staged = self._container(name, deadline)
        if staged is not None:
            self._owned(
                staged, site.site_id, role="candidate", run_id=run_id, attempt=attempt
            )
            self._docker(["rm", "-f", staged["Id"]], deadline)
        tag = f"patchpilot-candidate:{self.project_id}-{token}"
        image = self._image(tag, deadline)
        if image is not None:
            self._owned(
                image, site.site_id, role="candidate", run_id=run_id, attempt=attempt
            )
            active = self._container(f"patchpilot-{site.site_id}", deadline)
            if active is None or active.get("Image") != image["Id"]:
                self._docker(["image", "rm", tag], deadline)

    def prepare(self, *, timeout_s: float = 600) -> dict[str, Any]:
        """Reset only this workspace's fixtures; retain all records and recipes."""
        deadline = Deadline(timeout_s)
        for site in self.sites.values():
            for name in (
                f"patchpilot-{site.site_id}",
                f"patchpilot-orig-retained-{site.site_id}",
            ):
                info = self._container(name, deadline)
                if info is not None:
                    self._owned(info, site.site_id)
        digest = self._resolve_image(BASELINE_IMAGE, deadline)
        images = {}
        for site in self.sites.values():
            profile = self.manifest[site.site_id]["originalConfigProfile"] + ".ini"
            images[site.site_id] = self._build(
                site,
                f"patchpilot-baseline:{self.project_id}-{site.site_id}",
                digest,
                profile,
                self._labels(site.site_id, "fixture"),
                deadline,
            )
        report: dict[str, Any] = {
            "status": "COMPLETED",
            "sites_reset": [],
            "candidates_cleaned": [],
            "recipes_cleared": False,
        }
        names = self._docker(
            [
                "ps",
                "-a",
                "--filter",
                f"label=patchpilot.project={self.project_id}",
                "--format",
                "{{.Names}}",
            ],
            deadline,
        ).stdout.splitlines()
        for name in names:
            info = self._container(name, deadline)
            if info is None:
                continue
            labels = info.get("Config", {}).get("Labels") or {}
            site_id = labels.get("patchpilot.site_id")
            if labels.get("app") == "patchpilot-candidate" and site_id in self.sites:
                self._owned(info, site_id, role="candidate")
                self._docker(["rm", "-f", info["Id"]], deadline)
                report["candidates_cleaned"].append(info["Id"])
        for site in self.sites.values():
            for name in (
                f"patchpilot-{site.site_id}",
                f"patchpilot-orig-retained-{site.site_id}",
            ):
                info = self._container(name, deadline)
                if info is not None:
                    self._owned(info, site.site_id)
                    self._docker(["rm", "-f", info["Id"]], deadline)
            self._launch(
                site,
                f"patchpilot-{site.site_id}",
                images[site.site_id],
                self.manifest[site.site_id]["port"],
                f"baseline-{site.site_id}",
                {
                    **self._labels(site.site_id, "fixture"),
                    "patchpilot.base_digest": digest,
                },
                deadline,
            )
            self._wait(site.base_url, f"baseline-{site.site_id}", deadline)
            snapshot = self._inspect(site, deadline)
            checks = HttpVerifier(self).check(
                site, snapshot, "BASELINE", timeout_s=deadline.remaining()
            )
            if (
                snapshot.php_version != "8.3.35"
                or not snapshot.upload_progress_enabled
                or not checks_complete(site, checks)
            ):
                raise RuntimeError(
                    "Prepared baseline did not pass actual runtime and capability checks"
                )
            report["sites_reset"].append(
                {
                    "site_id": site.site_id,
                    "deployment_id": snapshot.deployment_id,
                    "image_id": snapshot.image_id,
                    "php_version": snapshot.php_version,
                    "checks_passed": len(checks),
                }
            )
        return report
