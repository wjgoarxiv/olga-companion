"""Antigravity OAuth and API client for OLGA Companion."""

from .constants import (
    CLIENT_ID,
    CLIENT_SECRET,
    SCOPES,
    TOKEN_ENDPOINT,
    DAILY_ENDPOINT,
    PROD_ENDPOINT,
    DEFAULT_PROJECT_ID,
    HEADERS,
    ANTIGRAVITY_MODELS,
    OPENAI_MODELS,
    COPILOT_MODELS,
    AUTH_PROVIDERS,
)
from .token import (
    OAuthTokens,
    TokenManager,
    parse_compound_token,
    is_token_expired,
    refresh_access_token,
    load_tokens,
    save_tokens,
)
from .client import AntigravityClient
from .streaming import (
    parse_stream,
    convert_tool_to_antigravity,
    convert_tools_to_antigravity,
)

__all__ = [
    # Constants
    "CLIENT_ID",
    "CLIENT_SECRET",
    "SCOPES",
    "TOKEN_ENDPOINT",
    "DAILY_ENDPOINT",
    "PROD_ENDPOINT",
    "DEFAULT_PROJECT_ID",
    "HEADERS",
    "ANTIGRAVITY_MODELS",
    "OPENAI_MODELS",
    "COPILOT_MODELS",
    "AUTH_PROVIDERS",
    # Token management
    "OAuthTokens",
    "TokenManager",
    "parse_compound_token",
    "is_token_expired",
    "refresh_access_token",
    "load_tokens",
    "save_tokens",
    # Client
    "AntigravityClient",
    # Streaming
    "parse_stream",
    "convert_tool_to_antigravity",
    "convert_tools_to_antigravity",
]
