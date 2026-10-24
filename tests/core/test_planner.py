"""Exercise the real Anthropic SDK over a local HTTP mock transport."""

import json
import os

import httpx2
import pytest
from anthropic import Anthropic

from patchpilot.core.assessment import assess
from patchpilot.core.domain import CheckResult
from patchpilot.core.planner import AnthropicPlanner, PlannerError
from patchpilot.core.ports import PlanningContext, PlanSource

from .test_assessment import original, passing_checks, policy, site

PLAN = {
    "targetImageAlias": "php83_patched",
    "configProfileId": "preserve_uploads",
    "rationale": "Update PHP while preserving the required upload size.",
}


def context():
    target, snapshot, current_policy = site(), original(), policy()
    return PlanningContext(
        target,
        snapshot,
        assess(target, snapshot, passing_checks(), current_policy),
        current_policy,
    )


def mock_planner(payload=None, *, stop_reason="end_turn", status=200):
    requests = []

    def respond(request):
        requests.append(request)
        if status != 200:
            return httpx2.Response(
                status,
                json={
                    "error": {
                        "type": "overloaded_error",
                        "message": "PRIVATE_UPSTREAM_DETAIL",
                    }
                },
            )
        text = json.dumps(PLAN if payload is None else payload)
        return httpx2.Response(
            200,
            json={
                "id": "msg_test_only",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": text}],
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 120, "output_tokens": 40},
            },
        )

    client = Anthropic(
        api_key="test-key-not-a-credential",
        base_url="https://api.anthropic.com",
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
    )
    return AnthropicPlanner(client, model="claude-sonnet-5-5"), requests


def test_anthropic_request_uses_a_strict_schema_and_returns_model_provenance():
    planner, requests = mock_planner()
    try:
        proposed = planner.propose(context(), (), timeout_s=5)
    finally:
        planner.close()

    assert proposed.source is PlanSource.MODEL
    assert proposed.plan.config_profile_id == "preserve_uploads"
    assert proposed.model_id == "claude-sonnet-5-5"
    assert proposed.input_tokens == 120 and proposed.output_tokens == 40
    assert planner.request_count == len(requests) == 1
    request = json.loads(requests[0].content)
    schema = request["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["targetImageAlias"]["enum"] == ["php83_patched"]
    assert request["max_tokens"] == 1024
    assert "tools" not in request
    assert requests[0].url.host == "api.anthropic.com"


def test_private_site_identity_and_raw_failure_messages_do_not_enter_the_prompt():
    planner, requests = mock_planner()
    try:
        planner.propose(
            context(),
            (CheckResult("upload_hash", False, "PRIVATE_FAILURE_MESSAGE"),),
            timeout_s=5,
        )
    finally:
        planner.close()

    body = requests[0].content.decode()
    assert "upload_hash" in body
    assert "PRIVATE_FAILURE_MESSAGE" not in body
    assert site().base_url not in body
    assert original().image_id not in body
    assert "test-key-not-a-credential" not in body


@pytest.mark.parametrize("reason", ["refusal", "max_tokens", "tool_use"])
def test_incomplete_or_refused_outputs_do_not_become_a_repair_plan(reason):
    planner, _ = mock_planner(stop_reason=reason)
    try:
        with pytest.raises(PlannerError):
            planner.propose(context(), (), timeout_s=5)
    finally:
        planner.close()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {**PLAN, "command": "run arbitrary commands"},
        {**PLAN, "targetImageAlias": "unknown_image"},
        {**PLAN, "configProfileId": "unknown_profile"},
        {**PLAN, "rationale": "x" * 501},
    ],
)
def test_malformed_or_unapproved_response_is_rejected_locally(payload):
    planner, _ = mock_planner(payload)
    try:
        with pytest.raises(PlannerError):
            planner.propose(context(), (), timeout_s=5)
    finally:
        planner.close()


def test_provider_errors_are_not_retried_or_exposed_as_successful_fallbacks():
    planner, requests = mock_planner(status=503)
    try:
        with pytest.raises(PlannerError) as caught:
            planner.propose(context(), (), timeout_s=5)
    finally:
        planner.close()

    assert planner.request_count == len(requests) == 1
    assert "PRIVATE_UPSTREAM_DETAIL" not in str(caught.value)
    assert "503" in str(caught.value)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_request_budget_does_not_call_the_provider(timeout):
    planner, requests = mock_planner()
    try:
        with pytest.raises(PlannerError):
            planner.propose(context(), (), timeout_s=timeout)
    finally:
        planner.close()

    assert planner.request_count == len(requests) == 0


def test_environment_configuration_requires_a_local_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(PlannerError, match="ANTHROPIC_API_KEY"):
        AnthropicPlanner.from_environment(env_file=tmp_path / "missing.env")


def test_local_env_loads_configuration_without_mutating_process_environment(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY=test-only-key\nANTHROPIC_MODEL=configured-model\n"
    )

    planner = AnthropicPlanner.from_environment(env_file=env_file)
    try:
        assert planner.model == "configured-model"
        assert planner.request_count == 0
        assert "ANTHROPIC_API_KEY" not in os.environ
    finally:
        planner.close()


def test_placeholder_key_is_rejected_before_any_provider_request(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=your-anthropic-api-key-here\n")

    with pytest.raises(PlannerError, match="ANTHROPIC_API_KEY"):
        AnthropicPlanner.from_environment(env_file=env_file)
