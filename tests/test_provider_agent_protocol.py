"""No-network contract tests for advertised chat providers."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import anyio
import pytest

from olga_companion.agent import chat, runtime, tools as agent_tools
from olga_companion.llm import copilot_auth, copilot_clients
from olga_companion.llm.antigravity import token as antigravity_token
from olga_companion.llm.antigravity.client import AntigravityClient
from olga_companion.llm.antigravity.streaming import convert_tools_to_antigravity
from olga_companion.llm.antigravity.token import OAuthTokens
from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient
from olga_companion.llm.protocol import ApiClient, StreamResult, fix_schema


def _antigravity_tokens() -> OAuthTokens:
    return OAuthTokens(
        access_token="antigravity-test-token",
        refresh_token="antigravity-test-refresh",
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _assert_agent_protocol(client: ApiClient | None, model: str) -> None:
    assert client is not None
    conversation = client.create_conversation(model)
    assert callable(conversation.add_user_message)
    assert callable(conversation.add_assistant_response)
    assert callable(conversation.add_tool_result)
    assert callable(conversation.add_nudge)
    assert callable(conversation.get_request_payload)
    assert inspect.iscoroutinefunction(client.stream_generate)


def test_copilot_real_builder_returns_agent_api_client_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid short-lived Copilot credential is available locally.
    monkeypatch.setattr(
        copilot_auth,
        "get_valid_copilot_token",
        lambda: "copilot-test-token",
    )

    # When: the production chat seam builds the advertised provider.
    client = chat._build_real_client("copilot", "gpt-5.4-mini", "medium")

    # Then: it satisfies the async ApiClient contract consumed by run_turn.
    _assert_agent_protocol(client, "gpt-5.4-mini")


def test_antigravity_real_builder_returns_agent_api_client_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: valid Antigravity credentials are available locally.
    tokens = _antigravity_tokens()
    monkeypatch.setattr(antigravity_token, "load_tokens", lambda: tokens)
    monkeypatch.setattr(copilot_clients, "load_tokens", lambda: tokens)

    # When: the production chat seam builds the advertised provider.
    client = chat._build_real_client(
        "antigravity",
        "gemini-3-pro-high",
        "medium",
    )

    # Then: it satisfies the async ApiClient contract consumed by run_turn.
    _assert_agent_protocol(client, "gemini-3-pro-high")


def test_copilot_real_builder_fails_closed_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(copilot_auth, "get_valid_copilot_token", lambda: None)
    assert chat._build_real_client("copilot", "gpt-5.4-mini", "medium") is None


def test_antigravity_real_builder_fails_closed_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(antigravity_token, "load_tokens", lambda: None)
    assert (
        chat._build_real_client(
            "antigravity",
            "gemini-3-pro-high",
            "medium",
        )
        is None
    )


async def _generate_with_live_tools(client: ApiClient, model: str) -> StreamResult:
    conversation = client.create_conversation(model)
    conversation.add_user_message("review the active case")
    return await client.stream_generate(
        conversation=conversation,
        model=model,
        system_instruction="Use tools for simulator evidence.",
        tools=agent_tools.tool_specs(),
    )


def test_copilot_agent_client_converts_flat_runtime_tool_specs_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the agent's real flat tool declaration and a transport-free delegate.
    captured_wire_tools: list[dict] = []
    monkeypatch.setattr(
        copilot_auth,
        "get_valid_copilot_token",
        lambda: "copilot-test-token",
    )

    async def convert_before_transport(delegate, **kwargs):
        captured_wire_tools.extend(delegate._convert_tools(kwargs["tools"]))
        return StreamResult(text="ready")

    monkeypatch.setattr(OpenAIChatApiClient, "stream_generate", convert_before_transport)
    client = chat._build_real_client("copilot", "gpt-5.4-mini", "medium")
    assert client is not None

    # When: a provider turn receives the same flat tool shape as runtime.run_turn.
    result = anyio.run(_generate_with_live_tools, client, "gpt-5.4-mini")

    # Then: every live declaration reaches the nested OpenAI function shape.
    assert result.text == "ready"
    specs = agent_tools.tool_specs()
    assert [item["function"]["name"] for item in captured_wire_tools] == [
        spec["name"] for spec in specs
    ]
    assert [item["function"]["parameters"] for item in captured_wire_tools] == [
        fix_schema(spec["parameters"]) for spec in specs
    ]
    side_effect_names = {
        name for name, tool in agent_tools.TOOLS.items() if tool.side_effect
    }
    for item in captured_wire_tools:
        if item["function"]["name"] in side_effect_names:
            assert "approval_token" not in item["function"]["parameters"]["properties"]
            assert "approval_token" not in item["function"]["parameters"].get("required", [])


def test_antigravity_agent_client_converts_flat_runtime_tool_specs_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the agent's real flat tool declaration and a transport-free raw client.
    tokens = _antigravity_tokens()
    captured_wire_tools: list[dict] = []
    monkeypatch.setattr(antigravity_token, "load_tokens", lambda: tokens)

    class RawClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return None

        async def stream_generate(self, **kwargs):
            captured_wire_tools.extend(convert_tools_to_antigravity(kwargs["tools"]))
            return {"text": "ready"}

    raw_client = RawClient()
    monkeypatch.setattr(
        AntigravityClient,
        "from_tokens",
        classmethod(lambda _cls, _tokens: raw_client),
    )
    client = chat._build_real_client(
        "antigravity",
        "gemini-3-pro-high",
        "medium",
    )
    assert client is not None

    # When: a provider turn receives the same flat tool shape as runtime.run_turn.
    result = anyio.run(_generate_with_live_tools, client, "gemini-3-pro-high")

    # Then: every live declaration reaches the native function shape.
    assert result.text == "ready"
    specs = agent_tools.tool_specs()
    assert [item["name"] for item in captured_wire_tools] == [
        spec["name"] for spec in specs
    ]
    assert [item["parameters"] for item in captured_wire_tools] == [
        fix_schema(spec["parameters"]) for spec in specs
    ]
    side_effect_names = {
        name for name, tool in agent_tools.TOOLS.items() if tool.side_effect
    }
    for item in captured_wire_tools:
        if item["name"] in side_effect_names:
            assert "approval_token" not in item["parameters"]["properties"]
            assert "approval_token" not in item["parameters"].get("required", [])


async def _collect_provider_failure(
    client: ApiClient,
    model: str,
) -> list[runtime.AgentEvent]:
    return [
        event
        async for event in runtime.run_turn(
            client,
            "inspect the active case",
            model=model,
        )
    ]


def test_copilot_provider_failure_is_redacted_after_real_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real provider builder and a secret-bearing transport failure.
    secret = "Bearer copilot-secret /private/customer/case.genkey"
    monkeypatch.setattr(
        copilot_auth,
        "get_valid_copilot_token",
        lambda: "copilot-test-token",
    )
    client = chat._build_real_client("copilot", "gpt-5.4-mini", "medium")
    assert client is not None

    async def fail_generation(**_kwargs) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(client, "stream_generate", fail_generation)

    # When: the agent runtime attempts the provider turn.
    events = anyio.run(_collect_provider_failure, client, "gpt-5.4-mini")

    # Then: the provider error is generic and the secret never reaches events.
    assert events == [
        runtime.AgentEvent(
            "error",
            {"message": "응답을 만들지 못했습니다. 공급자 연결을 확인하고 다시 시도하세요."},
        )
    ]
    assert secret not in repr(events)


def test_antigravity_provider_failure_is_redacted_after_real_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real provider builder and a secret-bearing transport failure.
    secret = "Bearer antigravity-secret /private/customer/case.genkey"
    tokens = _antigravity_tokens()
    monkeypatch.setattr(antigravity_token, "load_tokens", lambda: tokens)
    client = chat._build_real_client(
        "antigravity",
        "gemini-3-pro-high",
        "medium",
    )
    assert client is not None

    async def fail_generation(**_kwargs) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(client, "stream_generate", fail_generation)

    # When: the agent runtime attempts the provider turn.
    events = anyio.run(
        _collect_provider_failure,
        client,
        "gemini-3-pro-high",
    )

    # Then: the provider error is generic and the secret never reaches events.
    assert events == [
        runtime.AgentEvent(
            "error",
            {"message": "응답을 만들지 못했습니다. 공급자 연결을 확인하고 다시 시도하세요."},
        )
    ]
    assert secret not in repr(events)
