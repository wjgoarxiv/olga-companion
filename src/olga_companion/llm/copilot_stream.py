"""Async generation loops shared by the synchronous preview clients."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from .antigravity.client import AntigravityClient
from .antigravity.token import OAuthTokens
from .antigravity_adapter import AntigravityApiClient
from .copilot_errors import (
    _is_copilot_model_unsupported,
    _is_copilot_rate_limited,
    _note_provider_outcome,
    note_copilot_model_fallback,
    note_copilot_unsupported_model,
)
from .copilot_requests import (
    _DEFAULT_USER_PROMPT,
    adapt_openai_tools,
    copilot_models_to_try,
    generation_config,
)
from .copilot_transport import (
    create_copilot_chat_transport,
    create_openai_responses_transport,
)

logger = logging.getLogger(__name__)


async def stream_antigravity_preview(
    *,
    tokens: OAuthTokens,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    temperature: float,
) -> str:
    try:
        async with AntigravityClient.from_tokens(tokens) as raw_client:
            api_client = AntigravityApiClient(raw_client)
            conversation = api_client.create_conversation(model=model)
            conversation.add_user_message(user_prompt or _DEFAULT_USER_PROMPT)
            result = await api_client.stream_generate(
                conversation=conversation,
                model=model,
                system_instruction=system_prompt,
                tools=None,
                generation_config=generation_config(
                    max_output_tokens,
                    temperature,
                ),
            )
    except BaseException as exc:  # noqa: BROAD_EXCEPT_OK — record then re-raise
        _note_provider_outcome("antigravity", exc)
        raise
    _note_provider_outcome("antigravity", None)
    return result.text or ""


async def stream_openai_preview(
    *,
    access_token: str,
    extra_headers: dict[str, str],
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    temperature: float,
) -> str:
    api_client = create_openai_responses_transport(access_token, extra_headers)
    conversation = api_client.create_conversation(model=model)
    conversation.add_user_message(user_prompt or _DEFAULT_USER_PROMPT)
    result = await api_client.stream_generate(
        conversation=conversation,
        model=model,
        system_instruction=system_prompt,
        tools=None,
        generation_config=generation_config(max_output_tokens, temperature),
    )
    return result.text or ""


async def _run_copilot_models(
    requested_model: str,
    run: Callable[[str], Awaitable[str]],
) -> str:
    last_exc: BaseException | None = None
    for model in copilot_models_to_try(requested_model):
        try:
            text = await run(model)
        except BaseException as exc:  # noqa: BROAD_EXCEPT_OK — classify/re-raise
            last_exc = exc
            if _is_copilot_model_unsupported(exc):
                note_copilot_unsupported_model(model)
                continue
            if _is_copilot_rate_limited(exc):
                continue
            _note_provider_outcome("copilot", exc)
            raise
        _note_provider_outcome("copilot", None)
        if model != requested_model:
            note_copilot_model_fallback(requested_model, model)
        return text

    _note_provider_outcome("copilot", last_exc)
    assert last_exc is not None
    raise last_exc


async def stream_copilot_preview(
    *,
    token: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    temperature: float,
) -> str:
    api_client = create_copilot_chat_transport(token)

    async def run(candidate_model: str) -> str:
        conversation = api_client.create_conversation(model=candidate_model)
        conversation.add_user_message(user_prompt or _DEFAULT_USER_PROMPT)
        result = await api_client.stream_generate(
            conversation=conversation,
            model=candidate_model,
            system_instruction=system_prompt,
            tools=None,
            generation_config=generation_config(
                max_output_tokens,
                temperature,
            ),
        )
        return result.text or ""

    return await _run_copilot_models(model, run)


async def stream_copilot_tools(
    *,
    token: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
    tool_dispatch,
    max_rounds: int,
    on_tool_event,
    max_output_tokens: int,
    temperature: float,
) -> str:
    openai_tools = adapt_openai_tools(tools)
    api_client = create_copilot_chat_transport(token)

    async def run(candidate_model: str) -> str:
        conversation = api_client.create_conversation(model=candidate_model)
        conversation.add_user_message(user_prompt or _DEFAULT_USER_PROMPT)
        final_text = ""
        for _ in range(max(1, int(max_rounds))):
            result = await api_client.stream_generate(
                conversation=conversation,
                model=candidate_model,
                system_instruction=system_prompt,
                openai_tools=openai_tools or None,
                generation_config=generation_config(
                    max_output_tokens,
                    temperature,
                ),
            )
            tool_calls = result.tool_calls or []
            if not tool_calls:
                final_text = result.text or ""
                break
            conversation.add_assistant_response(
                result.text or "",
                tool_calls=tool_calls,
            )
            for tool_call in tool_calls:
                if on_tool_event:
                    try:
                        on_tool_event("tool", {"name": tool_call.name})
                    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — optional hook
                        logger.debug("Copilot tool progress hook failed")
                try:
                    output = tool_dispatch(
                        tool_call.name,
                        tool_call.args if isinstance(tool_call.args, dict) else {},
                    )
                except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — sanitized below
                    output = json.dumps(
                        {
                            "error": (
                                "Tool execution failed unexpectedly. "
                                "Retry the operation."
                            )
                        }
                    )
                conversation.add_tool_result(
                    tool_call.call_id,
                    tool_call.name,
                    output if isinstance(output, str) else str(output),
                )
            final_text = result.text or final_text
        return final_text

    return await _run_copilot_models(model, run)
