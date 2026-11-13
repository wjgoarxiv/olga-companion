"""Provider and safety contracts for G007 setup and patrol tools."""

from __future__ import annotations

import pytest

from olga_companion.agent import tools
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.llm.agent_clients import _adapt_runtime_tools
from olga_companion.llm.antigravity.streaming import convert_tools_to_antigravity
from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient
from olga_companion.llm.openai_responses_adapter import OpenAIResponsesApiClient
from olga_companion.llm.protocol import fix_schema


@pytest.mark.parametrize("name", ["simulation_setup", "run_patrol"])
def test_lifecycle_tool_schema_is_closed_read_only_and_provider_identical(name: str) -> None:
    tool = tools.TOOLS[name]
    schema = tool.parameters
    flat = {"name": name, "description": tool.description, "parameters": schema}
    adapted = _adapt_runtime_tools([flat])

    assert tool.side_effect is False
    assert tool.response_schema is not None
    assert schema["additionalProperties"] is False
    assert adapted is not None
    assert [
        OpenAIResponsesApiClient._convert_tools([flat])[0]["parameters"],
        OpenAIChatApiClient._convert_tools(adapted)[0]["function"]["parameters"],
        convert_tools_to_antigravity([flat])[0]["parameters"],
    ] == [fix_schema(schema)] * 3


def test_model_facing_output_target_is_the_managed_run_sandbox() -> None:
    schema = tools.TOOLS["simulation_setup"].parameters

    assert "case_id" not in schema["properties"]["binding"]["properties"]
    target = schema["properties"]["output_target"]["properties"]["relative_dir"]
    assert target == {"const": "managed-run-sandbox"}


def test_arbitrary_output_target_is_rejected_before_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["simulation_setup"],
        "handler",
        lambda value: calls.append(value) or {},
    )
    payload = {
        "binding": {
            "kind": "active_case",
            "source_sha256": "a" * 64,
        },
        "integration": {"end_time_s": 3600},
        "outputs": ["PT"],
        "runtime": {"candidate_id": "candidate_01", "runtime_id": "runtime_2022"},
        "timeout_s": 120,
        "output_target": {"relative_dir": "user-chosen-folder"},
        "context_generation": 1,
    }

    with pytest.raises(tools.ToolError, match="output_target|relative_dir|Invalid"):
        tools.dispatch("simulation_setup", payload)

    assert calls == []


def test_patrol_bounds_are_rejected_before_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["run_patrol"],
        "handler",
        lambda value: calls.append(value) or {},
    )

    with pytest.raises(tools.ToolError, match="deadline|max_polls|maximum|Invalid"):
        tools.dispatch(
            "run_patrol",
            {"run_id": "run-1", "deadline_s": 3601, "max_polls": 1000, "backoff_s": 30},
        )

    assert calls == []


def test_prompt_forbids_automatic_fix_publish_or_rerun() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "run_patrol" in prompt
    assert "never auto-apply" in prompt
    assert "never auto-rerun" in prompt
