"""Standalone CLI helper for fixture management (Task 03, Task 15)."""
import argparse
import json
import sys
from pathlib import Path
from patchpilot.runtime.reset import FleetResetManager
from patchpilot.runtime.deployment import DockerRuntimeAdapter
from patchpilot.runtime.verification import SiteVerifier


def main():
    parser = argparse.ArgumentParser(description="PatchPilot Fixture Runtime Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    status_parser = subparsers.add_parser("status", help="Inspect status of registered fleet sites")

    # reset
    reset_parser = subparsers.add_parser("reset", help="Reset fleet to baseline original state")
    reset_parser.add_argument("--clear-recipes", action="store_true", help="Clear cached recipes")

    # verify
    verify_parser = subparsers.add_parser("verify", help="Run HTTP verifications against fleet sites")
    verify_parser.add_argument("--site", type=str, help="Specific site ID to verify (default: all)")

    args = parser.parse_args()

    reset_mgr = FleetResetManager()
    adapter = DockerRuntimeAdapter()
    verifier = SiteVerifier()

    if args.command == "reset":
        print("Resetting PatchPilot fleet...")
        report = reset_mgr.reset_fleet(clear_recipes=args.clear_recipes)
        print(json.dumps(report, indent=2))

    elif args.command == "status":
        fleet = reset_mgr.load_fleet_manifest()
        for site in fleet:
            try:
                snap = adapter.inspect(site)
                print(f"[{site['id']}] RUNNING at {snap.endpoint} | PHP: {snap.php_version} | Upload Progress Mitigation: {not snap.session_upload_progress_enabled}")
            except Exception as e:
                print(f"[{site['id']}] OFFLINE or UNREACHABLE: {e}")

    elif args.command == "verify":
        fleet = reset_mgr.load_fleet_manifest()
        if args.site:
            fleet = [s for s in fleet if s["id"] == args.site]

        for site in fleet:
            print(f"--- Verifying site {site['id']} at {site['endpoint']} ---")
            results = verifier.check(site=site, endpoint=site["endpoint"], phase="BASELINE")
            for r in results:
                status_str = "PASS" if r.passed else f"FAIL ({r.error_message})"
                print(f"  [{status_str}] {r.name} ({r.duration_ms}ms)")


if __name__ == "__main__":
    main()
