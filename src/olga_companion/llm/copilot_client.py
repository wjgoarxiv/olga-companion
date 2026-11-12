"""Thin synchronous preview clients for Antigravity, OpenAI, and Copilot."""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK — sync provider protocol requires asyncio.run

from .antigravity.token import OAuthTokens, load_tokens
from .copilot_requests import (
    DEFAULT_OPENAI_PREVIEW_MODEL,
    _strip_provider_prefix,
)
from .copilot_stream import (
    stream_antigravity_preview,
    stream_copilot_preview,
    stream_copilot_tools,
    stream_openai_preview,
)
from .copilot_transport import (
    _resolve_openai_access_token,
    chatgpt_backend_headers,
)
from .openai_auth import load_tokens as load_openai_tokens


class AntigravityPreviewClient:
    """Sync preview client backed by the async Antigravity adapter."""

    def __init__(
        self,
        *,
        model: str,
        tokens: OAuthTokens | None = None,
        max_output_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> None:
        if tokens is None:
            tokens = load_tokens()
        if tokens is None:
            raise RuntimeError(  # noqa: GENERIC_ERR_OK — preserve public error
                "No Antigravity OAuth tokens found at "
                "~/.olga_copilot/tokens.json. Authenticate via the "
                "existing app login flow before constructing the real "
                "preview LLM adapter."
            )
        self._tokens = tokens
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature

    def __call__(self, *, system_prompt: str, user_prompt: str) -> str:
        return asyncio.run(self._generate(system_prompt, user_prompt))

    async def _generate(self, system_prompt: str, user_prompt: str) -> str:
        return await stream_antigravity_preview(
            tokens=self._tokens,
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
        )


class OpenAIPreviewClient:
    """Sync preview client backed by ChatGPT's Codex Responses surface."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_OPENAI_PREVIEW_MODEL,
        tokens: dict | None = None,
        max_output_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> None:
        if tokens is None:
            tokens = load_openai_tokens()
        if not tokens:
            raise RuntimeError(  # noqa: GENERIC_ERR_OK — preserve public error
                "No OpenAI tokens found at "
                "~/.olga_copilot/openai_tokens.json. Authenticate via "
                "the existing app login flow before constructing the "
                "real OpenAI preview client."
            )
        access_token = _resolve_openai_access_token(tokens)
        self._access_token = access_token
        self._extra_headers = chatgpt_backend_headers(access_token)
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature

    def __call__(self, *, system_prompt: str, user_prompt: str) -> str:
        return asyncio.run(self._generate(system_prompt, user_prompt))

    async def _generate(self, system_prompt: str, user_prompt: str) -> str:
        return await stream_openai_preview(
            access_token=self._access_token,
            extra_headers=self._extra_headers,
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
        )


class CopilotPreviewClient:
    """Sync text and tool-loop client for GitHub Copilot chat."""

    def __init__(
        self,
        *,
        model: str,
        token: str | None = None,
        max_output_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> None:
        if token is None:
            from .copilot_auth import get_valid_copilot_token

            token = get_valid_copilot_token()
        if not token:
            raise RuntimeError(  # noqa: GENERIC_ERR_OK — preserve public error
                "No GitHub Copilot token available. Authenticate via the app's "
                "Copilot device-code login before constructing the client."
            )
        self._token = token
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature

    def __call__(self, *, system_prompt: str, user_prompt: str) -> str:
        return asyncio.run(self._generate(system_prompt, user_prompt))

    async def _generate(self, system_prompt: str, user_prompt: str) -> str:
        return await stream_copilot_preview(
            token=self._token,
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
        )

    def generate_with_tools(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict],
        tool_dispatch,
        max_rounds: int = 4,
        on_tool_event=None,
    ) -> str:
        return asyncio.run(
            self._generate_with_tools(
                system_prompt,
                user_prompt,
                tools,
                tool_dispatch,
                max_rounds,
                on_tool_event,
            )
        )

    async def _generate_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict],
        tool_dispatch,
        max_rounds: int,
        on_tool_event,
    ) -> str:
        return await stream_copilot_tools(
            token=self._token,
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=tools,
            tool_dispatch=tool_dispatch,
            max_rounds=max_rounds,
            on_tool_event=on_tool_event,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
        )


def build_preview_client_from_env(
    *,
    model: str | None = None,
) -> AntigravityPreviewClient:
    from ..config import DEFAULT_LLM_MODEL

    chosen = model or _strip_provider_prefix(DEFAULT_LLM_MODEL)
    return AntigravityPreviewClient(model=chosen)


def build_openai_preview_client_from_env(
    *,
    model: str | None = None,
) -> OpenAIPreviewClient:
    return OpenAIPreviewClient(model=model or DEFAULT_OPENAI_PREVIEW_MODEL)


def build_copilot_preview_client_from_env(
    *,
    model: str | None = None,
) -> CopilotPreviewClient:
    from .antigravity.constants import DEFAULT_COPILOT_MODEL

    return CopilotPreviewClient(model=model or DEFAULT_COPILOT_MODEL)
