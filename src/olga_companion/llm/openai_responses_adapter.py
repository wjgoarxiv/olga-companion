"""
OpenAI Responses API adapter for OLGA Companion.

Handles the /responses endpoint with named SSE events, required for
Codex models (gpt-5.x-codex) and ChatGPT backend. Tracks function_call
items for tool result pairing.
"""
import asyncio
import base64
import json
import logging
import time
from typing import Any, Callable, Optional

from .codex_oauth_models import codex_models_to_try, is_codex_model_not_found
from .protocol import ConversationBuilder, StreamResult, ToolCall, fix_schema

logger = logging.getLogger(__name__)


def _note_codex_unsupported_model(model: str) -> None:
    try:
        from . import provider_runtime_status

        provider_runtime_status.record_unsupported_model("openai", model)
    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — status is best-effort
        logger.debug("Unable to record unsupported Codex model")


def _note_codex_model_fallback(requested: str, used: str) -> None:
    try:
        from . import provider_runtime_status

        provider_runtime_status.record_model_fallback(
            "openai", requested=requested, used=used
        )
    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — status is best-effort
        logger.debug("Unable to record Codex model fallback")


def _next_codex_model(requested: str) -> str | None:
    """First catalog model that is neither requested nor already rejected."""
    try:
        from . import provider_runtime_status

        unsupported = provider_runtime_status.unsupported_models("openai")
    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — status is best-effort
        unsupported = set()
    for candidate in codex_models_to_try(requested)[1:]:
        if candidate not in unsupported:
            return candidate
    return None


class OpenAIResponsesConversationBuilder:
    """Stateful message accumulator for OpenAI Responses API.

    Input format: [{"type": "message", "role": ..., "content": [...]}]
    Tool results require function_call + function_call_output pairs.
    Stores tool calls from add_assistant_response for pairing.
    """

    def __init__(self):
        self._input: list[dict] = []
        self._stored_tool_calls: dict[str, ToolCall] = {}  # call_id → ToolCall

    def add_user_message(
        self, text: str, images: Optional[list[bytes]] = None
    ) -> None:
        content_parts: list[dict] = [{"type": "input_text", "text": text}]
        if images:
            for img_bytes in images[:5]:  # Cap at 5 images
                content_parts.append({
                    "type": "input_image",
                    "image_url": (
                        f"data:image/png;base64,"
                        f"{base64.b64encode(img_bytes).decode('ascii')}"
                    ),
                })
        self._input.append({
            "type": "message",
            "role": "user",
            "content": content_parts,
        })

    def add_assistant_response(
        self,
        text: str,
        tool_calls: Optional[list[ToolCall]] = None,
        thought_signature: Any = None,
    ) -> None:
        if text and text.strip():
            self._input.append({
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            })
        # Store tool calls for add_tool_result pairing
        if tool_calls:
            for tc in tool_calls:
                self._stored_tool_calls[tc.call_id] = tc

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        tc = self._stored_tool_calls.get(call_id)
        # Responses API requires function_call item before function_call_output
        if not tc:
            logger.warning(f"add_tool_result: call_id {call_id!r} not in stored tool calls")
        if tc:
            self._input.append({
                "type": "function_call",
                "id": tc.item_id or call_id,
                "call_id": call_id,
                "name": name,
                "arguments": tc.raw_arguments or json.dumps(tc.args),
            })
        self._input.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": result,
        })

    def add_nudge(self, text: str) -> None:
        self._input.append({
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        })

    def get_request_payload(self) -> list[dict]:
        return list(self._input)


class OpenAIResponsesApiClient:
    """API client for OpenAI Responses API (Codex models + ChatGPT backend).

    Uses /responses endpoint with named SSE events instead of
    /chat/completions. Required for gpt-5.x-codex models.
    """

    def __init__(
        self,
        base_url: str,
        access_token: str,
        extra_headers: Optional[dict] = None,
        reasoning: Optional[dict] = None,
        text: Optional[dict] = None,
    ):
        self._base_url = base_url
        self._access_token = access_token
        self._extra_headers = extra_headers or {}
        # Reasoning-effort profile (from the selected variant); emitted into every
        # /responses body so the model's thinking depth matches the user's pick.
        self._reasoning = reasoning
        self._text = text

    def _request_body(
        self,
        *,
        model: str,
        system_instruction: str,
        input_payload: Any,
        resp_tools: Optional[list],
        force_tool: bool,
    ) -> dict:
        body: dict[str, Any] = {
            "model": model,
            "instructions": system_instruction,
            "input": input_payload,
            "stream": True,
            "store": False,
        }
        if self._reasoning:
            body["reasoning"] = dict(self._reasoning)
        if self._text:
            body["text"] = dict(self._text)
        if resp_tools:
            body["tools"] = resp_tools
            body["tool_choice"] = "required" if force_tool else "auto"
        return body

    def create_conversation(
        self, model: str = ""
    ) -> OpenAIResponsesConversationBuilder:
        return OpenAIResponsesConversationBuilder()

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
        import aiohttp
        from olga_companion import net

        input_payload = conversation.get_request_payload()

        # Convert tools from GenAI types.Tool → Responses API flat format
        resp_tools = self._convert_tools(tools) if tools else None

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }

        request_model = model
        body = self._request_body(
            model=request_model,
            system_instruction=system_instruction,
            input_payload=input_payload,
            resp_tools=resp_tools,
            force_tool=force_tool,
        )

        url = f"{self._base_url}/responses"
        start_time = time.time()

        response_text = ""
        tool_calls: dict[str, dict] = {}  # item_id → {call_id, name, arguments}
        response_id: Optional[str] = None

        # Retry loop: 2 transport attempts per model, fast-fail on 429.
        # Model rounds: the requested model, then one fallback when the
        # account rejects it with a 400 model_not_found.
        max_retries = 2
        retry_waits = [1, 2]

        for _model_round in range(2):
            try:
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
                                            "OpenAI API quota exceeded "
                                            "(insufficient_quota)."
                                        )
                                    raise ValueError(
                                        f"Rate limited (429) on {request_model}"
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
                                        f"Responses API error {resp.status}: "
                                        f"{error_text[:500]}"
                                    )

                                # Parse named SSE events
                                buffer = ""
                                current_event = ""
                                async for chunk in resp.content.iter_any():
                                    buffer += chunk.decode(
                                        "utf-8", errors="replace"
                                    )
                                    while "\n" in buffer:
                                        line, buffer = buffer.split("\n", 1)
                                        line = line.strip()

                                        if not line:
                                            current_event = ""
                                            continue

                                        if line.startswith("event: "):
                                            current_event = line[7:]
                                            continue

                                        if not line.startswith("data: "):
                                            continue

                                        try:
                                            data = json.loads(line[6:])
                                        except json.JSONDecodeError:
                                            continue

                                        # --- Handle events ---

                                        if (
                                            current_event
                                            == "response.output_text.delta"
                                        ):
                                            delta = data.get("delta", "")
                                            if delta:
                                                response_text += delta
                                                if on_token:
                                                    await on_token(delta)

                                        elif (
                                            current_event
                                            == "response.output_item.added"
                                        ):
                                            item = data.get("item", {})
                                            if item.get("type") == "function_call":
                                                item_id = item.get("id", "")
                                                tool_calls[item_id] = {
                                                    "call_id": item.get(
                                                        "call_id", ""
                                                    ),
                                                    "name": item.get("name", ""),
                                                    "arguments": "",
                                                }

                                        elif (
                                            current_event
                                            == "response.function_call_arguments.delta"
                                        ):
                                            item_id = data.get("item_id", "")
                                            if item_id in tool_calls:
                                                tool_calls[item_id][
                                                    "arguments"
                                                ] += data.get("delta", "")

                                        elif (
                                            current_event
                                            == "response.function_call_arguments.done"
                                        ):
                                            item_id = data.get("item_id", "")
                                            if item_id in tool_calls:
                                                tool_calls[item_id][
                                                    "arguments"
                                                ] = data.get(
                                                    "arguments",
                                                    tool_calls[item_id]["arguments"],
                                                )

                                        elif (
                                            current_event == "response.completed"
                                        ):
                                            resp_data = data.get("response", data)
                                            response_id = resp_data.get("id")
                                            usage = resp_data.get("usage", {})
                                            if usage and on_usage:
                                                await on_usage({
                                                    "prompt_tokens": usage.get(
                                                        "input_tokens", 0
                                                    ),
                                                    "completion_tokens": usage.get(
                                                        "output_tokens", 0
                                                    ),
                                                    "total_tokens": usage.get(
                                                        "total_tokens", 0
                                                    ),
                                                    "elapsed_seconds": round(
                                                        time.time() - start_time, 2
                                                    ),
                                                    "model": request_model,
                                                })

                        break  # Success

                    except ValueError:
                        raise

                    except Exception as e:
                        if attempt >= max_retries:
                            raise ValueError(
                                f"Responses API failed after {max_retries} "
                                f"attempts: {e}"
                            )
                        wait = retry_waits[min(attempt - 1, len(retry_waits) - 1)]
                        logger.warning(
                            f"Responses API attempt {attempt} failed: {e}. "
                            f"Retrying in {wait}s..."
                        )
                        await asyncio.sleep(wait)

                break  # Transport loop raised nothing: the model round is done.

            except ValueError as exc:
                if is_codex_model_not_found(exc, request_model):
                    # The account rejects this model: remember it, and retry
                    # once with the next supported model instead of failing.
                    _note_codex_unsupported_model(request_model)
                    if _model_round == 0:
                        fallback = _next_codex_model(model)
                        if fallback is not None:
                            request_model = fallback
                            body["model"] = request_model
                            continue
                raise

        if request_model != model:
            _note_codex_model_fallback(model, request_model)

        # Convert accumulated tool calls → ToolCall list
        tc_list: list[ToolCall] = []
        for item_id, tc_data in tool_calls.items():
            try:
                args = json.loads(tc_data["arguments"])
            except json.JSONDecodeError:
                args = {}
            tc_list.append(
                ToolCall(
                    name=tc_data["name"],
                    args=args,
                    call_id=tc_data["call_id"],
                    raw_arguments=tc_data["arguments"],
                    item_id=item_id,
                )
            )

        return StreamResult(
            text=response_text,
            tool_calls=tc_list,
            usage={"response_id": response_id} if response_id else {},
        )

    # ------------------------------------------------------------------
    # Tool format conversion
    # ------------------------------------------------------------------

    @classmethod
    def _convert_tools(cls, tools: list) -> list[dict]:
        """Convert a tool list → Responses API flat format.

        Responses API expects: {"type": "function", "name": ..., "parameters": ...}
        NOT the nested Chat format: {"type": "function", "function": {...}}

        Accepts either GenAI `types.Tool` objects (with `.function_declarations`)
        or the agent's flat spec dicts `{"name","description","parameters"}` — the
        latter is what `agent.tools.tool_specs()` yields, and `google.genai` is not
        a dependency, so the flat form is the real path here.
        """
        resp_tools: list[dict] = []
        for tool in tools:
            if isinstance(tool, dict):
                schema = fix_schema(tool.get("parameters") or {"type": "object", "properties": {}})
                resp_tools.append({
                    "type": "function",
                    "name": tool["name"],
                    "description": tool.get("description", "") or "",
                    "parameters": schema,
                })
                continue
            for decl in tool.function_declarations:
                schema = decl.parameters_json_schema or {
                    "type": "object",
                    "properties": {},
                }
                schema = fix_schema(schema)
                resp_tools.append({
                    "type": "function",
                    "name": decl.name,
                    "description": decl.description or "",
                    "parameters": schema,
                })
        return resp_tools
