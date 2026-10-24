"""Reset mechanism for PatchPilot demonstration fleet.

Restores the original registered fleet containers, optionally clears cached recipes,
and preserves all completed run records and event logs. Never affects unrelated containers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FleetResetManager:
    """Safely resets the local PatchPilot demo fleet to baseline configurations."""

    def __init__(self, workspace_root: Path | None = None):
        self.workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self.fleet_config_path = self.workspace_root / "config" / "fleet.json"
        self.recipes_dir = self.workspace_root / "var" / "recipes"
        self.runs_dir = self.workspace_root / "var" / "runs"

    def load_fleet_manifest(self) -> list[dict[str, Any]]:
        with open(self.fleet_config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def reset_fleet(self, clear_recipes: bool = False) -> dict[str, Any]:
        """Reset only owned PatchPilot containers, restoring baseline images and profiles.

        Completed run records in var/runs/ are strictly preserved.
        """
        from patchpilot.runtime.bridge import DockerRuntime

        reset_report = DockerRuntime(self.workspace_root).prepare(timeout_s=600)

        # 3. Clear recipes if requested
        if clear_recipes and self.recipes_dir.exists():
            if not self.recipes_dir.resolve().is_relative_to(
                self.workspace_root.resolve()
            ):
                raise RuntimeError("Recipe directory is outside the project workspace")
            for recipe_file in self.recipes_dir.glob("*.json"):
                if recipe_file.is_file() and not recipe_file.is_symlink():
                    recipe_file.unlink()
            reset_report["recipes_cleared"] = True

        return reset_report
