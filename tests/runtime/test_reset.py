"""Tests for Task 15: Scoped fleet reset preserving run records."""
import json
from pathlib import Path
import pytest
from patchpilot.runtime.reset import FleetResetManager
from patchpilot.runtime.deployment import DockerRuntimeAdapter


def test_fleet_manifest_valid():
    mgr = FleetResetManager()
    fleet = mgr.load_fleet_manifest()
    assert len(fleet) == 4
    site_ids = [s["id"] for s in fleet]
    assert "pantry-a" in site_ids
    assert "pantry-b" in site_ids
    assert "clinic-a" in site_ids
    assert "clinic-b" in site_ids


def test_fleet_reset_preserves_run_records(tmp_path):
    mgr = FleetResetManager()
    
    # Create a dummy run record in var/runs/
    workspace_root = mgr.workspace_root
    runs_dir = workspace_root / "var" / "runs" / "test-run-preservation"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / "run.json"
    run_file.write_text(json.dumps({"test": "keep-me"}), encoding="utf-8")

    try:
        # Perform reset
        report = mgr.reset_fleet(clear_recipes=True)
        assert report["status"] == "COMPLETED"
        assert len(report["sites_reset"]) == 4

        # Verify run record was strictly preserved
        assert run_file.exists()
        saved_data = json.loads(run_file.read_text(encoding="utf-8"))
        assert saved_data["test"] == "keep-me"

        # Verify that all 4 sites are now running at baseline
        adapter = DockerRuntimeAdapter()
        for site in mgr.load_fleet_manifest():
            snap = adapter.inspect(site)
            assert snap.php_version.startswith("8.3.35")
            assert snap.session_upload_progress_enabled is True

    finally:
        if run_file.exists():
            run_file.unlink()
        if runs_dir.exists():
            runs_dir.rmdir()
