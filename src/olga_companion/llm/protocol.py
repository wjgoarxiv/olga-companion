"""
API protocol definitions for OlgaCopilot backends.

Defines the contracts that all API adapters (Antigravity, OpenAI Chat,
OpenAI Responses) must implement. The agent loop uses these protocols
generically without knowing backend-specific details.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol


def fix_schema(schema: dict) -> dict:
    """Ensure arrays have 'items' and objects have 'properties' in JSON schemas."""
    if not isinstance(schema, dict):
        return schema
    schema = schema.copy()
    if schema.get("type") == "array" and "items" not in schema:
        schema["items"] = {}
    if schema.get("type") == "object" and "properties" not in schema:
        schema["properties"] = {}
    if "properties" in schema:
        schema["properties"] = {
            k: fix_schema(v) for k, v in schema["properties"].items()
        }
    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = fix_schema(schema["items"])
    return schema


@dataclass(frozen=True)
class ToolCall:
    """A tool/function call requested by the model."""

    name: str
    args: dict
    call_id: str = ""           # Unique ID for this call (tool_call_id / call_id)
    raw_arguments: str = ""     # Original JSON string for pass-through to Responses API
    item_id: str = ""           # Responses API function_call item ID


@dataclass
class StreamResult:
    """Accumulated result from a streaming API call."""

    text: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    thought_signature: Any = None  # Gemini 3 thought signature for multi-turn


class ConversationBuilder(Protocol):
    """
    Stateful message accumulator — adapters own the mutable message list.

    The agent loop calls generic add_* methods; each adapter handles
    backend-specific format internally. Tool results are buffered and
    flushed into the payload on the next get_request_payload() call.
    """

    def add_user_message(
        self, text: str, images: Optional[list[bytes]] = None
    ) -> None:
        """Add a user message, optionally with inline images."""
        ...

    def add_assistant_response(
        self,
        text: str,
        tool_calls: Optional[list[ToolCall]] = None,
        thought_signature: Any = None,
    ) -> None:
        """Add an assistant response, optionally with tool/function calls."""
        ...

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        """Add a tool execution result for a prior tool call."""
        ...

    def add_nudge(self, text: str) -> None:
        """Add a nudge/follow-up user message to re-prompt the model."""
        ...

    def get_request_payload(self) -> Any:
        """Return the backend-specific message/content payload.

        Flushes any buffered tool results before returning.
        """
        ...


class ApiClient(Protocol):
    """
    Streaming API client — wraps HTTP calls and SSE parsing.

    Each backend implements this protocol. The agent loop uses it
    generically; backend-specific concerns (auth, endpoints, SSE format)
    are encapsulated in the adapter.
    """

    async def stream_generate(
        self,
        *,
        conversation: ConversationBuilder,
        model: str,
        system_instruction: str,
        tools: Optional[list] = None,
        generation_config: Optional[dict] = None,
        force_tool: bool = False,
        on_token: Optional[Callable[[str], Any]] = None,
        on_thinking: Optional[Callable[[str], Any]] = None,
        on_usage: Optional[Callable[[dict], Any]] = None,
    ) -> StreamResult:
        """Stream a generation request and return accumulated result.

        Args:
            conversation: Stateful message accumulator with history.
            model: Model name (e.g., "gemini-3-pro", "gpt-4o").
            system_instruction: System prompt text.
            tools: Tool declarations (GenAI types.Tool during Phases 2-3).
            generation_config: Backend-specific generation parameters.
            force_tool: If True, force the model to call a tool.
            on_token: Callback for each streamed text token.
            on_thinking: Callback for thinking/reasoning text.
            on_usage: Callback for usage statistics.

        Returns:
            StreamResult with accumulated text, tool calls, and usage.
        """
        ...

    def create_conversation(self, model: str = "") -> ConversationBuilder:
        """Create a new empty ConversationBuilder for this backend.

        Args:
            model: Model name hint for format decisions (e.g., Gemini vs GPT-OSS).
        """
        ...
