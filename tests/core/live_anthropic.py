"""One live API request for a labeled synthetic scenario; never deploy a website."""

from __future__ import annotations

import json
from pathlib import Path

from patchpilot.core.assessment import assess
from patchpilot.core.domain import CheckResult, DeploymentSnapshot, Site
from patchpilot.core.planner import AnthropicPlanner, PlannerError
from patchpilot.core.policy import load_policy
from patchpilot.core.ports import PlanningContext


def main() -> int:
    target = Site(
        "clinic-a",
        "http://127.0.0.1:8083",
        "synthetic-upload-v1",
        frozenset({"homepage", "contact", "upload"}),
    )
    policy = load_policy(
        Path(__file__).resolve().parents[2] / "config/advisories.json",
        registered_site_ids=frozenset({target.site_id}),
    )
    snapshot = DeploymentSnapshot(
        target.site_id,
        "synthetic-original",
        "synthetic-image",
        "synthetic-application",
        "synthetic-configuration",
        "8.3.35",
        "apache2handler",
        True,
        base_url=target.base_url,
    )
    checks = tuple(
        CheckResult(key, True, "Synthetic planning input")
        for key in target.required_checks
    )
    assessment = assess(target, snapshot, checks, policy)
    try:
        planner = AnthropicPlanner.from_environment()
        try:
            proposed = planner.propose(
                PlanningContext(target, snapshot, assessment, policy), (), timeout_s=30
            )
        finally:
            planner.close()
    except PlannerError as error:
        print(
            json.dumps(
                {
                    "scenario": "synthetic-upload-planning",
                    "status": "failed",
                    "error": str(error),
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "scenario": "synthetic-upload-planning",
                "status": "provider-and-plan-contract-verified",
                "websiteDeployed": False,
                "source": proposed.source.value,
                "model": proposed.model_id,
                "profile": proposed.plan.config_profile_id,
                "providerRequests": planner.request_count,
                "inputTokens": proposed.input_tokens,
                "outputTokens": proposed.output_tokens,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
