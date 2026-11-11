"""
Antigravity API adapter for OlgaCopilot.

Wraps the existing AntigravityClient with the ApiClient/ConversationBuilder
protocol. The conversation builder manages contents in Antigravity format:
  [{"role": "user"/"model", "parts": [{"text": ...}]}]
"""
import base64
import json
import logging
from typing import Any, Callable, Optional

from .protocol import ConversationBuilder, StreamResult, ToolCall

logger = logging.getLogger(__name__)


class AntigravityConversationBuilder:
    """Stateful message accumulator for Antigravity API.

    Handles Gemini-specific thought_signature and GPT-OSS id fields
    based on the model name hint.
    """

    def __init__(self, model: str = ""):
        self._contents: list[dict] = []
        self._model = model
        self._pending_tool_results: list[dict] = []

    def _flush_tool_results(self) -> None:
        """Flush buffered tool results into a single user message."""
        if self._pending_tool_results:
            self._contents.append({
                "role": "user",
                "parts": list(self._pending_tool_results),
            })
            self._pending_tool_results = []

    def add_user_message(
        self, text: str, images: Optional[list[bytes]] = None
    ) -> None:
        self._flush_tool_results()
        parts: list[dict] = [{"text": text}]
        if images:
            for img_bytes in images:
                parts.append({
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64.b64encode(img_bytes).decode("ascii"),
                    }
                })
        self._contents.append({"role": "user", "parts": parts})

    def add_assistant_response(
        self,
        text: str,
        tool_calls: Optional[list[ToolCall]] = None,
        thought_signature: Any = None,
    ) -> None:
        self._flush_tool_results()
        if not tool_calls:
            if text:
                self._contents.append({
                    "role": "model",
                    "parts": [{"text": text}],
                })
            return

        parts: list[dict] = []
        # Gemini 3 requires thought_signature before functionCall parts
        is_gemini = "gemini" in self._model.lower()
        if thought_signature and is_gemini:
            parts.append({"thought_signature": thought_signature})
        # Preserve text before functionCall parts (model may produce both)
        if text:
            parts.append({"text": text})

        for tc in tool_calls:
            fc: dict = {"name": tc.name, "args": tc.args}
            if tc.call_id:
                fc["id"] = tc.call_id
            parts.append({"functionCall": fc})

        self._contents.append({"role": "model", "parts": parts})

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        is_gpt = "gpt" in self._model.lower()
        func_response: dict = {"name": name, "response": {"result": result}}
        # GPT-OSS requires 'id' field to match tool_call_id
        if is_gpt and call_id:
            func_response["id"] = call_id
        self._pending_tool_results.append({"functionResponse": func_response})

    def add_nudge(self, text: str) -> None:
        self._flush_tool_results()
        self._contents.append({"role": "user", "parts": [{"text": text}]})

    def get_request_payload(self) -> list[dict]:
        self._flush_tool_results()
        return list(self._contents)


class AntigravityApiClient:
    """API client adapter wrapping the existing AntigravityClient.

    Delegates HTTP/SSE handling to the underlying client and converts
    raw results into protocol-standard StreamResult objects.
    """

    def __init__(self, client: Any):
        """
        Args:
            client: AntigravityClient instance (from .antigravity.client).
        """
        self._client = client

    def create_conversation(self, model: str = "") -> AntigravityConversationBuilder:
        return AntigravityConversationBuilder(model=model)

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
        contents = conversation.get_request_payload()

        # Extract FunctionDeclaration objects from types.Tool list
        ag_tools = None
        if tools:
            ag_tools = [fd for t in tools for fd in t.function_declarations]

        tool_config = None
        if force_tool and ag_tools:
            tool_config = {"functionCallingConfig": {"mode": "ANY"}}

        # Normalize usage callback (Antigravity → standard keys)
        async def _on_usage(usage: dict) -> None:
            if on_usage:
                await on_usage({
                    "prompt_tokens": usage.get("promptTokenCount", 0),
                    "candidates_tokens": usage.get("candidatesTokenCount", 0),
                    "total_tokens": usage.get("totalTokenCount", 0),
                    "model": model,
                })

        result = await self._client.stream_generate(
            model=model,
            contents=contents,
            system_instruction=system_instruction,
            tools=ag_tools,
            generation_config=generation_config or {
                "maxOutputTokens": 4096,
                "temperature": 0.7,
            },
            on_token=on_token,
            on_thinking=on_thinking,
            on_tool_call=None,  # Collected in result dict
            on_usage=_on_usage,
            tool_config=tool_config,
        )

        # Convert raw tool call dicts → ToolCall dataclass
        tc_list: list[ToolCall] = []
        for fc in result.get("tool_calls", []):
            tc_list.append(ToolCall(
                name=fc.get("name", ""),
                args=fc.get("args", {}),
                call_id=fc.get("id", ""),
                raw_arguments=json.dumps(fc.get("args", {})),
            ))

        return StreamResult(
            text=result.get("text", ""),
            thinking=result.get("thinking", ""),
            tool_calls=tc_list,
            usage=result.get("usage", {}),
            thought_signature=result.get("thought_signature"),
        )
