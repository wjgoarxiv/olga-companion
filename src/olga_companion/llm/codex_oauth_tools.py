"""Bounded function-calling loop for the Codex Responses transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .codex_oauth_models import CodexAuthError, CodexCredentials
from .codex_oauth_responses import _raise_for_status, request_headers


TOOL_RESULT_MAX_CHARS = 6000
DEFAULT_MAX_TOOL_ROUNDS = 4


@dataclass(frozen=True, slots=True)
class ToolRoundBindings:
    """Transport and parser seams resolved by the compatibility facade."""

    endpoint: str
    client_factory: Callable[..., httpx.Client]
    mark_auth_failure: Callable[[], None]
    extract_text: Callable[[dict[str, Any]], str]
    accumulate_tool_calls: Callable[
        [dict[str, Any], dict[str, dict[str, Any]]], None
    ]


def accumulate_tool_call_events(
    event: dict[str, Any],
    pending: dict[str, dict[str, Any]],
) -> None:
    """Fold one Responses event into a function-call accumulator."""
    event_type = event.get("type", "")
    if event_type == "response.output_item.added":
        item = event.get("item") or {}
        if isinstance(item, dict) and item.get("type") == "function_call":
            item_id = item.get("id", "")
            pending[item_id] = {
                "call_id": item.get("call_id", ""),
                "name": item.get("name", ""),
                "arguments": "",
            }
    elif event_type == "response.function_call_arguments.delta":
        item_id = event.get("item_id", "")
        if item_id in pending:
            delta = event.get("delta")
            if isinstance(delta, str):
                pending[item_id]["arguments"] += delta
    elif event_type == "response.function_call_arguments.done":
        item_id = event.get("item_id", "")
        if item_id in pending:
            arguments = event.get("arguments")
            if isinstance(arguments, str):
                pending[item_id]["arguments"] = arguments


def stream_codex_round(
    *,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    bindings: ToolRoundBindings,
) -> tuple[str, list[dict[str, Any]]]:
    """POST one tool-enabled Responses round and parse text/function calls."""
    deltas: list[str] = []
    final_text = ""
    pending: dict[str, dict[str, Any]] = {}
    try:
        with bindings.client_factory(timeout=timeout) as client:
            with client.stream(
                "POST", bindings.endpoint, json=body, headers=headers
            ) as response:
                _raise_for_status(response, bindings.mark_auth_failure)
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except (json.JSONDecodeError, RecursionError, ValueError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    bindings.accumulate_tool_calls(event, pending)
                    text = bindings.extract_text(event)
                    if not text:
                        continue
                    if event.get("type") == "response.output_text.delta":
                        deltas.append(text)
                    else:
                        final_text = text
    except CodexAuthError:
        raise
    except httpx.HTTPError as exc:
        raise CodexAuthError(
            f"codex 모델 호출 네트워크 오류: {type(exc).__name__}"
        ) from None
    text = ("".join(deltas) or final_text).strip()
    tool_calls = [
        {
            "call_id": call["call_id"],
            "name": call["name"],
            "arguments": call["arguments"],
            "item_id": item_id,
        }
        for item_id, call in pending.items()
        if call.get("name")
    ]
    return text, tool_calls


def call_model_with_tools(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    config: dict[str, str],
    creds: CodexCredentials,
    tools: list[dict[str, Any]],
    tool_dispatch: Callable[[str, dict[str, Any]], str],
    max_rounds: int,
    tool_result_max_chars: int,
    on_tool_event: Callable[[str, dict[str, Any]], None] | None,
    stream_round: Callable[..., tuple[str, list[dict[str, Any]]]],
) -> str:
    """Run the bounded Codex function-calling loop."""
    if not creds.account_id:
        raise CodexAuthError(
            "codex 계정 정보를 확인할 수 없습니다. 다시 로그인해 주세요.",
            relogin_required=True,
        )
    headers = request_headers(creds)
    input_items: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": user_prompt}],
        }
    ]
    final_text = ""
    for _round in range(max(1, int(max_rounds))):
        body = {
            "model": model,
            "reasoning": {
                "effort": config["reasoning.effort"],
                "summary": config["reasoning.summary"],
            },
            "text": {"verbosity": config["text.verbosity"]},
            "instructions": system_prompt,
            "input": list(input_items),
            "tools": tools,
            "tool_choice": "auto",
            "store": False,
            "stream": True,
        }
        text, tool_calls = stream_round(body=body, headers=headers)
        if text:
            final_text = text
        if not tool_calls:
            break
        if text:
            input_items.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            )
        for tool_call in tool_calls:
            _append_tool_exchange(
                input_items,
                tool_call,
                tool_dispatch=tool_dispatch,
                tool_result_max_chars=tool_result_max_chars,
                on_tool_event=on_tool_event,
            )
    return final_text.strip()


def _append_tool_exchange(
    input_items: list[dict[str, Any]],
    tool_call: dict[str, Any],
    *,
    tool_dispatch: Callable[[str, dict[str, Any]], str],
    tool_result_max_chars: int,
    on_tool_event: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    name = tool_call["name"]
    raw_args = tool_call.get("arguments") or "{}"
    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            args = {}
    except (json.JSONDecodeError, RecursionError, ValueError):
        args = {}
    _emit_tool_event(on_tool_event, "tool_call", {"name": name, "arguments": args})
    try:
        result = tool_dispatch(name, args)
    except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        result = json.dumps({"error": f"tool '{name}' failed: {type(exc).__name__}"})
    if not isinstance(result, str):
        result = str(result)
    if len(result) > tool_result_max_chars:
        result = result[:tool_result_max_chars] + " …(truncated)"
    _emit_tool_event(on_tool_event, "tool_result", {"name": name, "chars": len(result)})
    input_items.extend(
        (
            {
                "type": "function_call",
                "id": tool_call.get("item_id") or tool_call["call_id"],
                "call_id": tool_call["call_id"],
                "name": name,
                "arguments": raw_args,
            },
            {
                "type": "function_call_output",
                "call_id": tool_call["call_id"],
                "output": result,
            },
        )
    )


def _emit_tool_event(
    callback: Callable[[str, dict[str, Any]], None] | None,
    phase: str,
    info: dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        callback(phase, info)
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        return
