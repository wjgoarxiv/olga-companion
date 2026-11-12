"""Protocol-native clients for the provider-agnostic chat agent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeAlias, assert_never

from . import copilot_auth
from .antigravity import token as antigravity_token
from .antigravity.client import AntigravityClient
from .antigravity.token import OAuthTokens
from .antigravity_adapter import (
    AntigravityApiClient,
    AntigravityConversationBuilder,
)
from .copilot_clients import COPILOT_CHAT_BASE_URL, COPILOT_EXTRA_HEADERS
from .openai_chat_adapter import OpenAIChatApiClient
from .protocol import ConversationBuilder, StreamResult, fix_schema

JsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)
TokenCallback: TypeAlias = Callable[[str], Awaitable[None]]
UsageCallback: TypeAlias = Callable[[dict[str, JsonValue]], Awaitable[None]]

@dataclass(frozen=True, slots=True)
class ProviderCredentialsUnavailableError(RuntimeError):
    provider: str

    def __str__(self) -> str:
        return f"No usable {self.provider} credential is connected."


@dataclass(frozen=True, slots=True)
class _FunctionDeclaration:
    name: str
    description: str
    parameters_json_schema: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _ProviderTool:
    function_declarations: tuple[_FunctionDeclaration, ...]


def _adapt_runtime_tools(
    tools: list[dict[str, JsonValue]] | None,
) -> list[_ProviderTool] | None:
    """Translate the agent's flat declarations to the legacy adapter shape."""
    if not tools:
        return None

    declarations: list[_FunctionDeclaration] = []
    for tool in tools:
        match tool.get("name"):
            case str() as name if name:
                pass
            case None | str() | int() | float() | bool() | list() | dict():
                continue
            case unreachable:
                assert_never(unreachable)
        match tool.get("description"):
            case str() as description:
                pass
            case None | int() | float() | bool() | list() | dict():
                description = ""
            case unreachable:
                assert_never(unreachable)
        match tool.get("parameters"):
            case dict() as parameters:
                schema = fix_schema(parameters)
            case None | str() | int() | float() | bool() | list():
                schema = {"type": "object", "properties": {}}
            case unreachable:
                assert_never(unreachable)
        declarations.append(
            _FunctionDeclaration(
                name=name,
                description=description,
                parameters_json_schema=schema,
            )
        )

    if not declarations:
        return None
    return [_ProviderTool(function_declarations=tuple(declarations))]


class CopilotAgentApiClient:
    """GitHub Copilot adapter implementing the agent ApiClient protocol."""

    def __init__(self, access_token: str) -> None:
        self._delegate = OpenAIChatApiClient(
            base_url=COPILOT_CHAT_BASE_URL,
            access_token=access_token,
            extra_headers=COPILOT_EXTRA_HEADERS,
        )

    def create_conversation(self, model: str = "") -> ConversationBuilder:
        return self._delegate.create_conversation(model)

    async def stream_generate(
        self,
        *,
        conversation: ConversationBuilder,
        model: str,
        system_instruction: str,
        tools: list[dict[str, JsonValue]] | None = None,
        generation_config: dict[str, JsonValue] | None = None,
        force_tool: bool = False,
        on_token: TokenCallback | None = None,
        on_thinking: TokenCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> StreamResult:
        return await self._delegate.stream_generate(
            conversation=conversation,
            model=model,
            system_instruction=system_instruction,
            tools=_adapt_runtime_tools(tools),
            generation_config=generation_config,
            force_tool=force_tool,
            on_token=on_token,
            on_thinking=on_thinking,
            on_usage=on_usage,
        )


class AntigravityAgentApiClient:
    """Antigravity adapter that owns and closes transport per generation."""

    def __init__(self, tokens: OAuthTokens) -> None:
        self._tokens = tokens

    def create_conversation(self, model: str = "") -> ConversationBuilder:
        return AntigravityConversationBuilder(model=model)

    async def stream_generate(
        self,
        *,
        conversation: ConversationBuilder,
        model: str,
        system_instruction: str,
        tools: list[dict[str, JsonValue]] | None = None,
        generation_config: dict[str, JsonValue] | None = None,
        force_tool: bool = False,
        on_token: TokenCallback | None = None,
        on_thinking: TokenCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> StreamResult:
        async with AntigravityClient.from_tokens(self._tokens) as raw_client:
            delegate = AntigravityApiClient(raw_client)
            return await delegate.stream_generate(
                conversation=conversation,
                model=model,
                system_instruction=system_instruction,
                tools=_adapt_runtime_tools(tools),
                generation_config=generation_config,
                force_tool=force_tool,
                on_token=on_token,
                on_thinking=on_thinking,
                on_usage=on_usage,
            )


def build_copilot_agent_client_from_env() -> CopilotAgentApiClient:
    token = copilot_auth.get_valid_copilot_token()
    if not token:
        raise ProviderCredentialsUnavailableError(provider="Copilot")
    return CopilotAgentApiClient(access_token=token)


def build_antigravity_agent_client_from_env() -> AntigravityAgentApiClient:
    tokens = antigravity_token.load_tokens()
    if tokens is None:
        raise ProviderCredentialsUnavailableError(provider="Antigravity")
    return AntigravityAgentApiClient(tokens=tokens)
