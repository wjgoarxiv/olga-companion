"""Compatibility facade for the split preview-provider client layer.

Request shaping, status/error handling, transport construction, async streaming,
and synchronous client ownership live in focused sibling modules. Existing
imports continue through this module.
"""

from __future__ import annotations

from .antigravity.client import AntigravityClient as AntigravityClient
from .antigravity.token import OAuthTokens as OAuthTokens
from .antigravity.token import load_tokens as load_tokens
from .antigravity_adapter import AntigravityApiClient as AntigravityApiClient
from .copilot_client import (
    AntigravityPreviewClient as AntigravityPreviewClient,
    CopilotPreviewClient as CopilotPreviewClient,
    OpenAIPreviewClient as OpenAIPreviewClient,
    build_copilot_preview_client_from_env as build_copilot_preview_client_from_env,
    build_openai_preview_client_from_env as build_openai_preview_client_from_env,
    build_preview_client_from_env as build_preview_client_from_env,
)
from .copilot_errors import (
    _is_copilot_model_unsupported as _is_copilot_model_unsupported,
    _is_copilot_rate_limited as _is_copilot_rate_limited,
    _looks_like_auth_error as _looks_like_auth_error,
    _note_provider_outcome as _note_provider_outcome,
)
from .copilot_requests import (
    CHATGPT_BACKEND_ACCEPT as CHATGPT_BACKEND_ACCEPT,
    CHATGPT_BACKEND_ORIGINATOR as CHATGPT_BACKEND_ORIGINATOR,
    CHATGPT_BACKEND_USER_AGENT as CHATGPT_BACKEND_USER_AGENT,
    COPILOT_CHAT_BASE_URL as COPILOT_CHAT_BASE_URL,
    COPILOT_EXTRA_HEADERS as COPILOT_EXTRA_HEADERS,
    DEFAULT_OPENAI_PREVIEW_MODEL as DEFAULT_OPENAI_PREVIEW_MODEL,
    OPENAI_PREVIEW_BASE_URL as OPENAI_PREVIEW_BASE_URL,
    _COPILOT_CHAT_FALLBACK_MODELS as _COPILOT_CHAT_FALLBACK_MODELS,
    _COPILOT_FALLBACK_PREFERENCE as _COPILOT_FALLBACK_PREFERENCE,
    _COPILOT_OWNER_ALLOWED_IDS as _COPILOT_OWNER_ALLOWED_IDS,
    _DEFAULT_USER_PROMPT as _DEFAULT_USER_PROMPT,
    _strip_provider_prefix as _strip_provider_prefix,
)
from .copilot_transport import (
    _extract_chatgpt_account_id as _extract_chatgpt_account_id,
    _resolve_openai_access_token as _resolve_openai_access_token,
    build_openai_agent_client_from_codex as build_openai_agent_client_from_codex,
)
from .openai_auth import load_tokens as load_openai_tokens
from .openai_auth import refresh_openai_token as refresh_openai_token
from .openai_auth import save_tokens as save_openai_tokens
from .openai_responses_adapter import (
    OpenAIResponsesApiClient as OpenAIResponsesApiClient,
)

__all__ = [
    "AntigravityApiClient",
    "AntigravityClient",
    "AntigravityPreviewClient",
    "CHATGPT_BACKEND_ACCEPT",
    "CHATGPT_BACKEND_ORIGINATOR",
    "CHATGPT_BACKEND_USER_AGENT",
    "COPILOT_CHAT_BASE_URL",
    "COPILOT_EXTRA_HEADERS",
    "CopilotPreviewClient",
    "DEFAULT_OPENAI_PREVIEW_MODEL",
    "OPENAI_PREVIEW_BASE_URL",
    "OAuthTokens",
    "OpenAIResponsesApiClient",
    "OpenAIPreviewClient",
    "build_copilot_preview_client_from_env",
    "build_openai_agent_client_from_codex",
    "build_openai_preview_client_from_env",
    "build_preview_client_from_env",
    "load_openai_tokens",
    "load_tokens",
    "refresh_openai_token",
    "save_openai_tokens",
]
