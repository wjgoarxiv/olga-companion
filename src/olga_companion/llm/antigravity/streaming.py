"""SSE streaming utilities for Antigravity API responses."""

import json
import logging
import asyncio
import re
from typing import Any, AsyncIterator, Callable, Optional, Union, Awaitable

logger = logging.getLogger(__name__)

# GPT-OSS raw control tokens that should never reach the user.
# Pattern matches <|start|>, <|channel|>, <|message|>, <|call|>, <|end|>, etc.
_RAW_TOKEN_RE = re.compile(r"<\|[a-z_]+\|>")

# Full raw tool-call line pattern:
#   <|start|>assistant<|channel|>commentary to=TOOL code<|message|>JSON<|call|>
_RAW_TOOL_CALL_RE = re.compile(
    r"<\|start\|>assistant<\|channel\|>.*?<\|call\|>",
    re.DOTALL,
)


def _strip_raw_tokens(text: str) -> str:
    """Strip GPT-OSS raw control tokens and invisible Unicode from text output.

    Returns cleaned text, or empty string if the entire text was control tokens.
    """
    # First strip full raw tool-call lines
    cleaned = _RAW_TOOL_CALL_RE.sub("", text)
    # Then strip any remaining individual control tokens
    cleaned = _RAW_TOKEN_RE.sub("", cleaned)
    # Strip zero-width characters that break KaTeX rendering (U+200B, U+200C, U+200D, U+FEFF)
    cleaned = cleaned.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return cleaned


async def _maybe_await(callback: Callable, *args) -> None:
    """Call a callback, awaiting if it's a coroutine function."""
    if callback is None:
        return
    result = callback(*args)
    if asyncio.iscoroutine(result):
        await result


async def _process_part(
    part: dict,
    state: dict,
    on_token: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None,
    on_thinking: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None,
    on_tool_call: Optional[Callable[[dict], Union[None, Awaitable[None]]]] = None,
) -> None:
    """Process a single SSE part consistently across streamed and tail-buffer paths."""
    if "thought" in part:
        if isinstance(part["thought"], str) and part["thought"]:
            thinking_text = part["thought"]
            state["thinking"] += thinking_text
            await _maybe_await(on_thinking, thinking_text)
        elif part["thought"] is True and "text" in part:
            thinking_text = part["text"]
            state["thinking"] += thinking_text
            await _maybe_await(on_thinking, thinking_text)
        elif "text" in part:
            text = _strip_raw_tokens(part["text"])
            if text:
                state["text"] += text
                await _maybe_await(on_token, text)
    elif "text" in part:
        text = _strip_raw_tokens(part["text"])
        if text:
            state["text"] += text
            await _maybe_await(on_token, text)

    if "thought_signature" in part:
        state["thought_signature"] = part["thought_signature"]

    if "functionCall" in part:
        func_call = part["functionCall"]
        if state.get("thought_signature"):
            func_call["thought_signature"] = state["thought_signature"]
        if "id" in part:
            func_call["id"] = part["id"]
        state["tool_calls"].append(func_call)
        await _maybe_await(on_tool_call, func_call)


async def _process_sse_payload(
    data: dict,
    state: dict,
    on_token: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None,
    on_thinking: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None,
    on_tool_call: Optional[Callable[[dict], Union[None, Awaitable[None]]]] = None,
    on_usage: Optional[Callable[[dict], Union[None, Awaitable[None]]]] = None,
) -> None:
    """Process one parsed SSE payload consistently."""
    if "response" in data:
        data = data["response"]

    candidates = data.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            await _process_part(part, state, on_token, on_thinking, on_tool_call)
        state["candidates"].append(candidate)

    if "usageMetadata" in data:
        state["usage"] = data["usageMetadata"]
        await _maybe_await(on_usage, state["usage"])


async def parse_stream(
    response_iterator: AsyncIterator[bytes],
    on_token: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None,
    on_thinking: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None,
    on_tool_call: Optional[Callable[[dict], Union[None, Awaitable[None]]]] = None,
    on_usage: Optional[Callable[[dict], Union[None, Awaitable[None]]]] = None,
) -> dict:
    """
    Parse SSE stream from Antigravity API.

    Args:
        response_iterator: Async iterator of SSE chunks
        on_token: Callback for each text token (can be sync or async)
        on_thinking: Callback for thinking/reasoning text (can be sync or async)
        on_tool_call: Callback for each function call (can be sync or async)
        on_usage: Callback for usage metadata (can be sync or async)

    Returns:
        Accumulated response with all parts
    """
    state = {
        "text": "",
        "thinking": "",
        "tool_calls": [],
        "usage": {},
        "candidates": [],
        "thought_signature": None,
    }

    buffer = ""

    async for chunk in response_iterator:
        # Decode bytes to string
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")

        buffer += chunk

        # Process complete SSE lines
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith(":"):
                continue

            # Parse SSE data line
            if line.startswith("data: "):
                data_str = line[6:]  # Remove "data: " prefix

                # Skip "[DONE]" signal
                if data_str == "[DONE]":
                    continue

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse SSE data: {e}")
                    continue

                await _process_sse_payload(
                    data,
                    state,
                    on_token=on_token,
                    on_thinking=on_thinking,
                    on_tool_call=on_tool_call,
                    on_usage=on_usage,
                )

    # Process remaining buffer
    if buffer.strip():
        if buffer.strip().startswith("data: "):
            data_str = buffer.strip()[6:]
            if data_str and data_str != "[DONE]":
                try:
                    data = json.loads(data_str)
                    await _process_sse_payload(
                        data,
                        state,
                        on_token=on_token,
                        on_thinking=on_thinking,
                        on_tool_call=on_tool_call,
                        on_usage=on_usage,
                    )
                except json.JSONDecodeError:
                    pass

    # Final safety-net strip of any raw control tokens that slipped through
    state["text"] = _strip_raw_tokens(state["text"])

    return {
        "text": state["text"],
        "thinking": state["thinking"],
        "tool_calls": state["tool_calls"],
        "usage": state["usage"],
        "candidates": state["candidates"],
        "thought_signature": state["thought_signature"],  # Include for function response
    }


def convert_tool_to_antigravity(tool: Any) -> dict:
    """
    Convert google-genai FunctionDeclaration to Antigravity format.

    Args:
        tool: google-genai FunctionDeclaration or dict

    Returns:
        Antigravity-compatible function declaration
    """
    # Already a dict
    if isinstance(tool, dict):
        # Convert from snake_case to camelCase if needed
        result = {}
        if "name" in tool:
            result["name"] = tool["name"]
        if "description" in tool:
            result["description"] = tool["description"]
        if "parameters_json_schema" in tool:
            result["parameters"] = tool["parameters_json_schema"]
        elif "parameters" in tool:
            result["parameters"] = tool["parameters"]
        return result

    # google-genai FunctionDeclaration object
    result = {
        "name": getattr(tool, "name", "unknown"),
    }

    if hasattr(tool, "description") and tool.description:
        result["description"] = tool.description

    # Handle parameters
    if hasattr(tool, "parameters_json_schema") and tool.parameters_json_schema:
        result["parameters"] = tool.parameters_json_schema
    elif hasattr(tool, "parameters") and tool.parameters:
        result["parameters"] = tool.parameters

    return result


def convert_tools_to_antigravity(tools: list) -> list[dict]:
    """
    Convert list of tools to Antigravity format.

    Args:
        tools: List of google-genai FunctionDeclarations or dicts

    Returns:
        List of Antigravity-compatible function declarations
    """
    return [convert_tool_to_antigravity(tool) for tool in tools]
