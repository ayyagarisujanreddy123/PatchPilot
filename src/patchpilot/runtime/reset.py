"""Reset mechanism for PatchPilot demonstration fleet.

Restores the original registered fleet containers, optionally clears cached recipes,
and preserves all completed run records and event logs. Never affects unrelated containers.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess

logger = logging.getLogger(__name__)


class FleetResetManager:
    """Safely resets the local PatchPilot demo fleet to baseline configurations."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self.fleet_config_path = self.workspace_root / "config" / "fleet.json"
        self.recipes_dir = self.workspace_root / "var" / "recipes"
        self.runs_dir = self.workspace_root / "var" / "runs"

    def load_fleet_manifest(self) -> List[Dict[str, Any]]:
        with open(self.fleet_config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _run_docker(self, args: List[str], check: bool = False) -> subprocess.CompletedProcess:
        cmd = ["docker"] + args
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def reset_fleet(self, clear_recipes: bool = False) -> Dict[str, Any]:
        """Reset only owned PatchPilot containers, restoring baseline images and profiles.

        Completed run records in var/runs/ are strictly preserved.
        """
        fleet = self.load_fleet_manifest()
        reset_report: Dict[str, Any] = {
            "status": "COMPLETED",
            "sites_reset": [],
            "candidates_cleaned": [],
            "recipes_cleared": False
        }

        # 1. Clean up any lingering candidate containers matching label app=patchpilot-candidate
        cand_list = self._run_docker([
            "ps", "-a", "-q",
            "--filter", "label=app=patchpilot-candidate"
        ])
        if cand_list.returncode == 0 and cand_list.stdout.strip():
            cids = cand_list.stdout.strip().split()
            self._run_docker(["rm", "-f"] + cids)
            reset_report["candidates_cleaned"] = cids

        # 2. Reset each registered fleet site
        fixtures_dir = self.workspace_root / "fixtures"

        for site in fleet:
            site_id = site["id"]
            port = site["port"]
            container_name = f"patchpilot-{site_id}"
            retained_name = f"patchpilot-orig-retained-{site_id}"
            orig_image = site.get("originalImage", "php:8.3.35-apache")
            config_profile = site.get("originalConfigProfile", "pantry-default")
            profile_file = f"{config_profile}.ini" if not config_profile.endswith(".ini") else config_profile
            tag = f"patchpilot-baseline:{site_id}"

            # Remove any retained and active containers for this site
            self._run_docker(["rm", "-f", container_name, retained_name])

            # Build baseline image
            self._run_docker([
                "build",
                "-t", tag,
                "--build-arg", f"BASE_IMAGE={orig_image}",
                "--build-arg", f"CONFIG_PROFILE={profile_file}",
                str(fixtures_dir)
            ], check=True)

            # Launch baseline container
            dep_id = f"baseline-{site_id}"
            run_cmd = [
                "run", "-d",
                "--name", container_name,
                "-p", f"127.0.0.1:{port}:80",
                "-e", f"SITE_ID={site_id}",
                "-e", f"ORG_NAME={site.get('organization', site.get('name', ''))}",
                "-e", f"ORG_TAGLINE={site.get('tagline', '')}",
                "-e", f"CAPABILITIES={','.join(site.get('requiredCapabilities', []))}",
                "-e", f"DEPLOYMENT_ID={dep_id}",
                "--label", "app=patchpilot-fixture",
                "--label", f"patchpilot.site_id={site_id}",
                "--label", "patchpilot.managed_by=patchpilot",
                tag
            ]
            self._run_docker(run_cmd, check=True)

            reset_report["sites_reset"].append({
                "site_id": site_id,
                "port": port,
                "deployment_id": dep_id,
                "image": orig_image,
                "profile": config_profile
            })

        # 3. Clear recipes if requested
        if clear_recipes and self.recipes_dir.exists():
            for recipe_file in self.recipes_dir.glob("*.json"):
                try:
                    recipe_file.unlink()
                except Exception as e:
                    logger.warning("Could not delete recipe %s: %e", recipe_file, e)
            reset_report["recipes_cleared"] = True

        return reset_report
