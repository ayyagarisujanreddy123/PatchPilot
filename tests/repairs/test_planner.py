import json
from types import SimpleNamespace

import pytest

from patchpilot.repairs.configuration import TARGETS
from patchpilot.repairs.errors import ConnectedRepairError
from patchpilot.repairs.planner import AnthropicConfigPlanner


class Stream:
    def __init__(self, data, stop="end_turn"):
        self.text = json.dumps(data)
        self.text_stream = iter([self.text[:8], self.text[8:]])
        self.message = SimpleNamespace(
            stop_reason=stop,
            content=[SimpleNamespace(type="text", text=self.text)],
            model="test-anthropic",
            id="test-message",
            usage=SimpleNamespace(input_tokens=20, output_tokens=30),
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_final_message(self):
        return self.message

    def close(self):
        pass


def propose(data, stop="end_turn"):
    calls, progress = [], []

    def stream(**kwargs):
        calls.append(kwargs)
        return Stream(data, stop)

    planner = AnthropicConfigPlanner(
        SimpleNamespace(messages=SimpleNamespace(stream=stream))
    )
    result = planner.propose(
        settings={**dict.fromkeys(TARGETS, "On"), "PRIVATE_CONFIG": "PRIVATE_VALUE"},
        runtime={"php_version": "8.3.36"},
        checks=[],
        capabilities=["homepage", "upload"],
        progress=progress.append,
    )
    return result, calls, progress


def valid():
    return {
        "rationale": "Hide diagnostics while retaining server logging and upload limits.",
        "changes": [{"key": key, "value": value} for key, value in TARGETS.items()],
    }


def test_real_stream_chunks_are_reported_and_only_normalized_settings_are_sent():
    result, calls, progress = propose(valid())
    assert result.provider_message_id == "test-message"
    assert result.input_tokens == 20 and result.output_tokens == 30
    assert "8 characters received" in progress[1]
    assert "PRIVATE_VALUE" not in json.dumps(calls)
    assert "PRIVATE_CONFIG" not in json.dumps(calls)
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize(
    "data",
    [
        {"rationale": "Invalid", "changes": [{"key": "memory_limit", "value": "On"}]},
        {"rationale": "Invalid", "changes": [{"key": "display_errors", "value": "On"}]},
        {
            "rationale": "Invalid",
            "changes": [{"key": "expose_php", "value": "Off"}] * 2,
        },
        {"rationale": "Invalid", "changes": [], "command": "unapproved"},
    ],
)
def test_unapproved_model_fields_targets_and_duplicate_settings_are_rejected(data):
    with pytest.raises(ConnectedRepairError, match="policy"):
        propose(data)


def test_incomplete_provider_output_never_becomes_a_patch():
    with pytest.raises(ConnectedRepairError, match="policy"):
        propose(valid(), "max_tokens")
