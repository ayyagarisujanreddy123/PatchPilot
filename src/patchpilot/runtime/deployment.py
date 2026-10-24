"""Docker deployment adapter for PatchPilot fixtures and candidates.

Implements inspection, staging, activation, restoration, and cleanup
for registered local targets.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


def find_free_port() -> int:
    """Find an available loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class DeploymentSnapshot:
    """Observed state of a deployed container."""
    site_id: str
    container_id: str
    container_name: str
    endpoint: str
    port: int
    image_id: str
    image_tag: str
    php_version: str
    php_sapi: str
    deployment_id: str
    session_upload_progress_enabled: bool
    status: str
    raw_probe: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateSpec:
    """Specification of an isolated staged candidate."""
    candidate_id: str
    site_id: str
    run_id: str
    attempt: int
    container_id: str
    container_name: str
    endpoint: str
    port: int
    derived_image_tag: str
    derived_image_id: str
    base_image: str
    config_profile: str


class DockerRuntimeAdapter:
    """Manages Docker container lifecycles for PatchPilot sites."""

    def __init__(self, workspace_root: Optional[Path] = None):
        # src/patchpilot/runtime/deployment.py -> parents[3] is workspace root
        self.workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self.fixtures_dir = self.workspace_root / "fixtures"

    def _run_docker(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """Execute a docker CLI command with logging."""
        cmd = ["docker"] + args
        res = subprocess.run(cmd, capture_output=True, text=True)
        if check and res.returncode != 0:
            raise RuntimeError(f"Docker command failed: {' '.join(cmd)}\nStderr: {res.stderr}")
        return res

    def inspect(self, site: Dict[str, Any]) -> DeploymentSnapshot:
        """Inspect an active site and query its HTTP runtime probe."""
        site_id = site["id"]
        endpoint = site.get("endpoint", f"http://127.0.0.1:{site.get('port')}")
        container_name = f"patchpilot-{site_id}"

        # Check container inspection
        res = self._run_docker(["inspect", container_name], check=False)
        container_id = ""
        image_tag = site.get("originalImage", "unknown")
        image_id = ""
        if res.returncode == 0:
            try:
                info = json.loads(res.stdout)[0]
                container_id = info.get("Id", "")[:12]
                image_id = info.get("Image", "")
            except Exception:
                pass

        # Probe HTTP endpoint
        probe_url = f"{endpoint}/runtime.php"
        try:
            req = urllib.request.Request(probe_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                probe_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Failed to query runtime probe at {probe_url}: {e}")

        return DeploymentSnapshot(
            site_id=site_id,
            container_id=container_id,
            container_name=container_name,
            endpoint=endpoint,
            port=site.get("port", 80),
            image_id=image_id,
            image_tag=image_tag,
            php_version=probe_data.get("php_version", "unknown"),
            php_sapi=probe_data.get("php_sapi", "unknown"),
            deployment_id=probe_data.get("deployment_id", "unknown"),
            session_upload_progress_enabled=bool(probe_data.get("session_upload_progress_enabled")),
            status="RUNNING",
            raw_probe=probe_data
        )

    def stage(
        self,
        site: Dict[str, Any],
        base_image: str,
        config_profile: str,
        run_id: str,
        attempt: int = 1
    ) -> CandidateSpec:
        """Build an immutable candidate image and launch it on an isolated port."""
        site_id = site["id"]
        candidate_port = find_free_port()
        candidate_id = f"{site_id}-cand-{run_id}-{attempt}"
        container_name = f"patchpilot-cand-{site_id}-{run_id}-{attempt}"
        derived_tag = f"patchpilot-candidate:{site_id}-{run_id}-{attempt}"

        profile_file = f"{config_profile}.ini" if not config_profile.endswith(".ini") else config_profile

        # Build candidate image
        build_args = [
            "build",
            "-t", derived_tag,
            "--build-arg", f"BASE_IMAGE={base_image}",
            "--build-arg", f"CONFIG_PROFILE={profile_file}",
            str(self.fixtures_dir)
        ]
        self._run_docker(build_args, check=True)

        # Inspect built image ID
        img_res = self._run_docker(["image", "inspect", derived_tag, "--format", "{{.Id}}"], check=True)
        derived_image_id = img_res.stdout.strip()

        # Run candidate container on isolated loopback port
        run_args = [
            "run", "-d",
            "--name", container_name,
            "-p", f"127.0.0.1:{candidate_port}:80",
            "-e", f"SITE_ID={site_id}",
            "-e", f"ORG_NAME={site.get('organization', site.get('name', ''))}",
            "-e", f"ORG_TAGLINE={site.get('tagline', '')}",
            "-e", f"CAPABILITIES={','.join(site.get('requiredCapabilities', []))}",
            "-e", f"DEPLOYMENT_ID={candidate_id}",
            "--label", "app=patchpilot-candidate",
            "--label", f"patchpilot.site_id={site_id}",
            "--label", f"patchpilot.run_id={run_id}",
            derived_tag
        ]
        container_res = self._run_docker(run_args, check=True)
        container_id = container_res.stdout.strip()[:12]

        candidate_endpoint = f"http://127.0.0.1:{candidate_port}"

        # Wait for candidate readiness
        ready = False
        start_time = time.time()
        while time.time() - start_time < 30:
            try:
                with urllib.request.urlopen(f"{candidate_endpoint}/runtime.php", timeout=2) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)

        if not ready:
            self._run_docker(["rm", "-f", container_name], check=False)
            raise TimeoutError(f"Candidate {candidate_id} failed to become ready within 30 seconds.")

        return CandidateSpec(
            candidate_id=candidate_id,
            site_id=site_id,
            run_id=run_id,
            attempt=attempt,
            container_id=container_id,
            container_name=container_name,
            endpoint=candidate_endpoint,
            port=candidate_port,
            derived_image_tag=derived_tag,
            derived_image_id=derived_image_id,
            base_image=base_image,
            config_profile=config_profile
        )

    def activate(
        self,
        site: Dict[str, Any],
        candidate: CandidateSpec
    ) -> DeploymentSnapshot:
        """Activate the verified candidate at the original site address."""
        site_id = site["id"]
        original_port = site["port"]
        live_container_name = f"patchpilot-{site_id}"
        retained_container_name = f"patchpilot-orig-retained-{site_id}"

        # 1. Stop original container and rename it to retained
        inspect_orig = self._run_docker(["inspect", live_container_name], check=False)
        if inspect_orig.returncode == 0:
            self._run_docker(["rm", "-f", retained_container_name], check=False)
            self._run_docker(["stop", live_container_name], check=False)
            self._run_docker(["rename", live_container_name, retained_container_name], check=False)

        # 2. Launch live container using the exact derived image that passed staging
        new_dep_id = f"live-{site_id}-{candidate.run_id}"
        run_args = [
            "run", "-d",
            "--name", live_container_name,
            "-p", f"127.0.0.1:{original_port}:80",
            "-e", f"SITE_ID={site_id}",
            "-e", f"ORG_NAME={site.get('organization', site.get('name', ''))}",
            "-e", f"ORG_TAGLINE={site.get('tagline', '')}",
            "-e", f"CAPABILITIES={','.join(site.get('requiredCapabilities', []))}",
            "-e", f"DEPLOYMENT_ID={new_dep_id}",
            "--label", "app=patchpilot-live",
            "--label", f"patchpilot.site_id={site_id}",
            candidate.derived_image_tag
        ]
        self._run_docker(run_args, check=True)

        # 3. Wait for readiness at original address
        endpoint = site.get("endpoint", f"http://127.0.0.1:{original_port}")
        ready = False
        start_time = time.time()
        while time.time() - start_time < 30:
            try:
                with urllib.request.urlopen(f"{endpoint}/runtime.php", timeout=2) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)

        if not ready:
            raise RuntimeError(f"Activated container failed readiness check at {endpoint}")

        return self.inspect(site)

    def restore(self, site: Dict[str, Any]) -> DeploymentSnapshot:
        """Restore the retained original container if activation or live check fails."""
        site_id = site["id"]
        live_container_name = f"patchpilot-{site_id}"
        retained_container_name = f"patchpilot-orig-retained-{site_id}"

        # Remove failed live container
        self._run_docker(["rm", "-f", live_container_name], check=False)

        # Rename retained container back to live name and start it
        rename_res = self._run_docker(["rename", retained_container_name, live_container_name], check=False)
        if rename_res.returncode != 0:
            raise RuntimeError(f"Could not find or rename retained original container {retained_container_name}")

        self._run_docker(["start", live_container_name], check=True)

        # Wait for restored container readiness
        endpoint = site.get("endpoint", f"http://127.0.0.1:{site.get('port')}")
        ready = False
        start_time = time.time()
        while time.time() - start_time < 30:
            try:
                with urllib.request.urlopen(f"{endpoint}/runtime.php", timeout=2) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)

        if not ready:
            raise RuntimeError(f"Restored container failed to answer readiness probe at {endpoint}")

        return self.inspect(site)

    def cleanup(self, candidate: CandidateSpec) -> Dict[str, Any]:
        """Remove candidate container and staging resources."""
        res = self._run_docker(["rm", "-f", candidate.container_name], check=False)
        return {
            "candidate_id": candidate.candidate_id,
            "container_name": candidate.container_name,
            "cleaned": res.returncode == 0
        }
