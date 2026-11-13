"""
OpenAI Chat Completions API adapter for OLGA Companion.

Handles both OpenAI direct and GitHub Copilot backends via the
/chat/completions endpoint with SSE streaming.
"""
import asyncio
import base64
import json
import logging
import time
from typing import Any, Callable, Optional

from .protocol import ConversationBuilder, StreamResult, ToolCall, fix_schema

logger = logging.getLogger(__name__)


_TOP_LEVEL_CONDITIONAL_KEYS = ("oneOf", "anyOf", "allOf")
_FALLBACK_CONDITIONAL_NOTE = "Additional conditional rules are enforced by the server."


def _required_names(node: object) -> list[str] | None:
    if not isinstance(node, dict):
        return None
    required = node.get("required")
    if (
        isinstance(required, list)
        and required
        and all(isinstance(name, str) for name in required)
    ):
        return list(required)
    return None


def _simple_condition_names(node: object) -> list[str] | None:
    """Required names only when the if-branch constrains nothing else.

    A branch like {"properties": {...}, "required": [...]} names a closed
    shape, not a plain "when X" trigger, so it gets the fallback note."""
    if not isinstance(node, dict) or set(node) != {"required"}:
        return None
    return _required_names(node)


def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _conditional_note(parameters: object) -> str:
    """State top-level oneOf/anyOf/allOf branches in words.

    Only the simple if-required/then-required shape gets a generated sentence
    (both sides holding nothing but "required"); anything else falls back to
    the server-enforces note."""
    if not isinstance(parameters, dict):
        return ""
    parts: list[str] = []
    fallback = False
    for key in _TOP_LEVEL_CONDITIONAL_KEYS:
        branches = parameters.get(key)
        if branches is None:
            continue
        if not isinstance(branches, list):
            fallback = True
            continue
        for branch in branches:
            given = _simple_condition_names(branch.get("if")) if isinstance(branch, dict) else None
            needed = _required_names(branch.get("then")) if isinstance(branch, dict) else None
            if given is None or needed is None:
                fallback = True
                continue
            verb = "is" if len(needed) == 1 else "are"
            parts.append(
                f"When {_join_names(given)} is given, {_join_names(needed)} {verb} also required."
            )
    if fallback or not parts:
        parts.append(_FALLBACK_CONDITIONAL_NOTE)
    return " ".join(parts)


class OpenAIChatConversationBuilder:
    """Stateful message accumulator for OpenAI Chat Completions API.

    Messages format: [{"role": "user"/"assistant"/"system"/"tool", "content": ...}]
    """

    def __init__(self):
        self._messages: list[dict] = []

    def add_user_message(
        self, text: str, images: Optional[list[bytes]] = None
    ) -> None:
        if images:
            content_parts: list[dict] = [{"type": "text", "text": text}]
            for img_bytes in images:
                b64 = base64.b64encode(img_bytes).decode("ascii")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            self._messages.append({"role": "user", "content": content_parts})
        else:
            self._messages.append({"role": "user", "content": text})

    def add_assistant_response(
        self,
        text: str,
        tool_calls: Optional[list[ToolCall]] = None,
        thought_signature: Any = None,
    ) -> None:
        if not tool_calls and not (text and text.strip()):
            # No content and no tool calls is not a valid Chat Completions message.
            return
        msg: dict = {"role": "assistant", "content": text or None}
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.raw_arguments or json.dumps(tc.args),
                    },
                }
                for tc in tool_calls
            ]
        self._messages.append(msg)

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        self._messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": result,
        })

    def add_nudge(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})

    def get_request_payload(self) -> list[dict]:
        return list(self._messages)


class OpenAIChatApiClient:
    """API client for OpenAI Chat Completions (OpenAI direct + GitHub Copilot).

    Owns HTTP request/response handling and SSE parsing. Authentication
    details (base_url, token, headers) are provided at construction.
    """

    def __init__(
        self,
        base_url: str,
        access_token: str,
        extra_headers: Optional[dict] = None,
        default_temperature: Optional[float] = 0.7,
    ):
        self._base_url = base_url
        self._access_token = access_token
        self._extra_headers = extra_headers or {}
        self._default_temperature = default_temperature

    def create_conversation(self, model: str = "") -> OpenAIChatConversationBuilder:
        return OpenAIChatConversationBuilder()

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
        openai_tools: Optional[list] = None,
    ) -> StreamResult:
        import aiohttp
        from olga_companion import net

        gen_cfg = generation_config or {}
        messages = (
            [{"role": "system", "content": system_instruction}]
            + conversation.get_request_payload()
        )

        # `openai_tools` is for callers that already hold OpenAI-chat-shaped tool
        # specs ({"type":"function","function":{...}}); the tool-calling Copilot
        # path passes these directly. Otherwise convert GenAI tools or flat specs.
        if openai_tools is None:
            openai_tools = self._convert_tools(tools) if tools else None

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": gen_cfg.get("maxOutputTokens", 4096),
            "stream": True,
        }
        # Some OpenAI-compatible endpoints (e.g. Anthropic) refuse `temperature`
        # for certain models, so it is sent only when explicitly configured.
        temperature = gen_cfg.get("temperature", self._default_temperature)
        if temperature is not None:
            body["temperature"] = temperature
        if openai_tools:
            body["tools"] = openai_tools
            if force_tool:
                body["tool_choice"] = "required"

        url = f"{self._base_url}/chat/completions"
        start_time = time.time()

        response_text = ""
        tool_calls_accumulated: dict[int, dict] = {}

        # Retry loop: 2 attempts, fast-fail on 429
        max_retries = 2

        for attempt in range(1, max_retries + 1):
            try:
                async with net.aiohttp_session() as session:
                    async with session.post(
                        url, json=body, headers=headers
                    ) as resp:
                        if resp.status == 429:
                            error_body = await resp.text()
                            if "insufficient_quota" in error_body:
                                raise ValueError(
                                    "OpenAI API quota exceeded (insufficient_quota)."
                                )
                            raise ValueError(
                                f"Rate limited (429) on {model}"
                            )
                        if resp.status == 401:
                            raise ValueError("Authentication failed (401)")
                        if resp.status == 403:
                            error_body = await resp.text()
                            raise ValueError(
                                f"Forbidden (403): {error_body[:200]}"
                            )
                        if resp.status == 413:
                            raise ValueError("Payload too large (413)")
                        if resp.status != 200:
                            error_text = await resp.text()
                            raise ValueError(
                                f"OpenAI API error {resp.status}: "
                                f"{error_text[:500]}"
                            )

                        # Parse SSE stream
                        buffer = ""
                        async for chunk in resp.content.iter_any():
                            buffer += chunk.decode("utf-8", errors="replace")
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                line = line.strip()
                                if not line:
                                    continue
                                if line == "data: [DONE]":
                                    break
                                if not line.startswith("data: "):
                                    continue
                                try:
                                    data = json.loads(line[6:])
                                except json.JSONDecodeError:
                                    continue

                                choices = data.get("choices", [])
                                if not choices:
                                    # Usage might be sent outside choices
                                    usage = data.get("usage")
                                    if usage and on_usage:
                                        await on_usage({
                                            "prompt_tokens": usage.get(
                                                "prompt_tokens", 0
                                            ),
                                            "completion_tokens": usage.get(
                                                "completion_tokens", 0
                                            ),
                                            "total_tokens": usage.get(
                                                "total_tokens", 0
                                            ),
                                            "elapsed_seconds": round(
                                                time.time() - start_time, 2
                                            ),
                                            "model": model,
                                        })
                                    continue

                                delta = choices[0].get("delta", {})

                                # Text content
                                content = delta.get("content")
                                if content:
                                    response_text += content
                                    if on_token:
                                        await on_token(content)

                                # Tool calls (streamed incrementally)
                                for tc in delta.get("tool_calls", []):
                                    idx = tc.get("index", 0)
                                    tc_id = tc.get("id")
                                    func = tc.get("function", {})
                                    if tc_id:
                                        tool_calls_accumulated[idx] = {
                                            "id": tc_id,
                                            "name": func.get("name", ""),
                                            "arguments": func.get(
                                                "arguments", ""
                                            ),
                                        }
                                    elif idx in tool_calls_accumulated:
                                        tool_calls_accumulated[idx][
                                            "arguments"
                                        ] += func.get("arguments", "")

                                # Inline usage
                                usage = data.get("usage")
                                if usage and on_usage:
                                    await on_usage({
                                        "prompt_tokens": usage.get(
                                            "prompt_tokens", 0
                                        ),
                                        "completion_tokens": usage.get(
                                            "completion_tokens", 0
                                        ),
                                        "total_tokens": usage.get(
                                            "total_tokens", 0
                                        ),
                                        "elapsed_seconds": round(
                                            time.time() - start_time, 2
                                        ),
                                        "model": model,
                                    })

                break  # Success

            except ValueError:
                raise  # 429/401/413 — propagate immediately

            except Exception as e:
                if attempt >= max_retries:
                    raise ValueError(
                        f"OpenAI Chat API failed after {max_retries} "
                        f"attempts: {e}"
                    )
                # Exponential backoff: 2s, 4s
                wait = float(2 ** attempt)
                logger.warning(
                    f"OpenAI Chat attempt {attempt} failed: {e}. "
                    f"Retrying in {wait:.1f}s..."
                )
                await asyncio.sleep(wait)

        # Convert accumulated tool calls → ToolCall list
        tc_list: list[ToolCall] = []
        for idx in sorted(tool_calls_accumulated.keys()):
            tc_data = tool_calls_accumulated[idx]
            try:
                args = json.loads(tc_data["arguments"])
            except json.JSONDecodeError:
                args = {}
            tc_list.append(
                ToolCall(
                    name=tc_data["name"],
                    args=args,
                    call_id=tc_data["id"],
                    raw_arguments=tc_data["arguments"],
                )
            )

        return StreamResult(text=response_text, tool_calls=tc_list)

    # ------------------------------------------------------------------
    # Tool format conversion
    # ------------------------------------------------------------------

    @classmethod
    def _convert_tools(cls, tools: list) -> list[dict]:
        """Convert tools to nested Chat format: {"type":"function","function":{...}}.

        Accepts GenAI tools (`.function_declarations`) and the agent's flat specs
        `{"name","description","parameters"}` from `tool_specs()`.
        """
        openai_tools: list[dict] = []
        for tool in tools:
            if isinstance(tool, dict):
                parameters = tool.get("parameters") or {"type": "object", "properties": {}}
                # Anthropic's OpenAI-compatible endpoint rejects top-level
                # oneOf/anyOf/allOf, so the provider payload drops those keys
                # and restates the rule in the description. The server still
                # enforces the full schema at dispatch.
                note = ""
                if isinstance(parameters, dict) and any(
                    key in parameters for key in _TOP_LEVEL_CONDITIONAL_KEYS
                ):
                    note = _conditional_note(parameters)
                    parameters = {
                        key: value
                        for key, value in parameters.items()
                        if key not in _TOP_LEVEL_CONDITIONAL_KEYS
                    }
                schema = fix_schema(parameters)
                description = tool.get("description", "") or ""
                if note:
                    description = f"{description} {note}" if description else note
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": description,
                            "parameters": schema,
                        },
                    }
                )
                continue
            for decl in tool.function_declarations:
                schema = decl.parameters_json_schema or {
                    "type": "object",
                    "properties": {},
                }
                schema = fix_schema(schema)
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": decl.name,
                        "description": decl.description or "",
                        "parameters": schema,
                    },
                })
        return openai_tools
