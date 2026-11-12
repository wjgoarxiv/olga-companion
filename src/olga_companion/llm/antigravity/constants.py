"""Antigravity OAuth constants and endpoints for OLGA Companion."""

import os


def _read_secret_env(*names: str) -> str:
    """Read a credential from env vars while ignoring placeholder values."""
    placeholder_values = {
        "",
        "your-client-id.apps.googleusercontent.com",
        "your-client-secret",
    }
    for name in names:
        value = os.environ.get(name, "").strip().strip('"').strip("'")
        if value and value not in placeholder_values:
            return value
    return ""

def _load_provisioned() -> dict:
    """Load build-baked OAuth secrets from the gitignored `_provisioned_secrets`
    module that `scripts/build_tauri_sidecar.ps1` writes (and PyInstaller bundles)
    before freezing. The frozen sidecar has no `.env` on a user's machine, so this
    is how distributed builds get the antigravity creds. Returns {} when absent
    (dev runs from `.env`)."""
    try:
        from . import _provisioned_secrets as p  # type: ignore  # noqa: PLC0415
    except Exception:
        return {}
    return {
        "CLIENT_ID": getattr(p, "CLIENT_ID", ""),
        "CLIENT_SECRET": getattr(p, "CLIENT_SECRET", ""),
    }


def _resolve_credential(env_value: str, provisioned_value) -> str:
    """env wins; else the build-baked value; else empty. Whitespace/None → empty."""
    if env_value:
        return env_value
    if isinstance(provisioned_value, str) and provisioned_value.strip():
        return provisioned_value.strip()
    return ""


_PROVISIONED = _load_provisioned()

# OAuth 2.0 Client Credentials (Google Cloud Code / Antigravity).
# Resolution order: env (.env, dev) → build-baked `_provisioned_secrets` (frozen build) → empty.
CLIENT_ID = _resolve_credential(
    _read_secret_env("ANTIGRAVITY_CLIENT_ID", "OAUTH_GOOGLE_CLIENT_ID"),
    _PROVISIONED.get("CLIENT_ID", ""),
)
CLIENT_SECRET = _resolve_credential(
    _read_secret_env("ANTIGRAVITY_CLIENT_SECRET", "OAUTH_GOOGLE_CLIENT_SECRET"),
    _PROVISIONED.get("CLIENT_SECRET", ""),
)


def require_antigravity_oauth_credentials() -> None:
    """Fail closed when Antigravity OAuth credentials are not configured."""
    if CLIENT_ID and CLIENT_SECRET:
        return
    raise RuntimeError(
        "Antigravity OAuth credentials are not configured. "
        "Set ANTIGRAVITY_CLIENT_ID/ANTIGRAVITY_CLIENT_SECRET or reuse "
        "OAUTH_GOOGLE_CLIENT_ID/OAUTH_GOOGLE_CLIENT_SECRET in your .env."
    )

# OAuth Scopes
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

# Token Refresh Endpoint
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Antigravity API Endpoints (try daily first, fallback to prod)
DAILY_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com"
PROD_ENDPOINT = "https://cloudcode-pa.googleapis.com"

# Streaming API Path
STREAM_PATH = "/v1internal:streamGenerateContent"
STREAM_PARAMS = "alt=sse"

# Default Project ID
DEFAULT_PROJECT_ID = "rising-fact-p41fc"

# Request Headers (MUST match the official Antigravity client exactly).
# 2026-06-08 — Google rejected "antigravity/1.15.8" as "out of date". The User-Agent
# version tracks the VS Code base version in product.json (Antigravity is a VS Code fork),
# captured from the locally installed Antigravity (%LOCALAPPDATA%\Programs\antigravity\
# resources\app\product.json -> version). Bump alongside the client; ideType must be
# ANTIGRAVITY (not IDE_UNSPECIFIED) per the current API.
ANTIGRAVITY_CLIENT_VERSION = "1.107.0"
HEADERS = {
    "User-Agent": f"antigravity/{ANTIGRAVITY_CLIENT_VERSION} windows/amd64",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": '{"ideType":"ANTIGRAVITY","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
    "Content-Type": "application/json",
    "x-goog-api-key": "",  # Must be present but EMPTY
}

# Available Models via Antigravity
# NOTE: Model names must match EXACTLY what Antigravity API expects
# These are the official model IDs from the Antigravity API spec
# Updated: 2026-04-24
ANTIGRAVITY_MODELS = {
    # Gemini Models
    "gemini-3.1-pro": {
        "name": "gemini-3.1-pro",
        "display_name": "Gemini 3.1 Pro",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-3-pro-high": {
        "name": "gemini-3-pro-high",
        "display_name": "Gemini 3 Pro (High)",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-3-pro-low": {
        "name": "gemini-3-pro-low",
        "display_name": "Gemini 3 Pro (Low)",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-3-flash": {
        "name": "gemini-3-flash",
        "display_name": "Gemini 3 Flash",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-2.5-pro": {
        "name": "gemini-2.5-pro",
        "display_name": "Gemini 2.5 Pro",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-2.5-flash": {
        "name": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    # Gemini 3.1 Flash Lite (released 2026-03-03)
    "gemini-3.1-flash-lite": {
        "name": "gemini-3.1-flash-lite",
        "display_name": "Gemini 3.1 Flash Lite",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    # Claude Models (via Antigravity)
    "claude-opus-4-7": {
        "name": "claude-opus-4-7",
        "display_name": "Claude Opus 4.7",
        "provider": "anthropic",
        "max_tokens": 128000,
        "context_window": 200000,
    },
    "claude-opus-4-6": {
        "name": "claude-opus-4-6",
        "display_name": "Claude Opus 4.6",
        "provider": "anthropic",
        "max_tokens": 128000,
        "context_window": 200000,
    },
    "claude-sonnet-4-6": {
        "name": "claude-sonnet-4-6",
        "display_name": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "max_tokens": 64000,
        "context_window": 200000,
    },
}

# Available Models via OpenAI API (direct)
# Updated: 2026-04-24
OPENAI_MODELS = {
    # GPT-5.5 family
    "gpt-5.5": {
        "name": "gpt-5.5",
        "display_name": "GPT-5.5",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 1000000,
    },
    # GPT-5.4 family — gpt-5.4 and gpt-5.4-mini were dropped by OpenAI
    # on 2026-06-05 (calls now 400); only the nano tier survives here.
    "gpt-5.4-nano": {
        "name": "gpt-5.4-nano",
        "display_name": "GPT-5.4 Nano",
        "provider": "openai",
        "max_tokens": 64000,
        "context_window": 128000,
    },
    "gpt-5.3-codex": {
        "name": "gpt-5.3-codex",
        "display_name": "GPT-5.3 Codex",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    "gpt-5.3-codex-spark": {
        "name": "gpt-5.3-codex-spark",
        "display_name": "GPT-5.3 Codex Spark",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 128000,
    },
    "gpt-5.2-codex": {
        "name": "gpt-5.2-codex",
        "display_name": "GPT-5.2 Codex",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    "gpt-5.2": {
        "name": "gpt-5.2",
        "display_name": "GPT-5.2",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    "gpt-5.1-codex": {
        "name": "gpt-5.1-codex",
        "display_name": "GPT-5.1 Codex",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    "gpt-5.1": {
        "name": "gpt-5.1",
        "display_name": "GPT-5.1",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    "gpt-5": {
        "name": "gpt-5",
        "display_name": "GPT-5",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    "gpt-5-mini": {
        "name": "gpt-5-mini",
        "display_name": "GPT-5 Mini",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    "o4-mini": {
        "name": "o4-mini",
        "display_name": "o4 Mini",
        "provider": "openai",
        "max_tokens": 100000,
        "context_window": 200000,
    },
    "o3-pro": {
        "name": "o3-pro",
        "display_name": "o3 Pro",
        "provider": "openai",
        "max_tokens": 100000,
        "context_window": 200000,
    },
    "o3": {
        "name": "o3",
        "display_name": "o3",
        "provider": "openai",
        "max_tokens": 100000,
        "context_window": 200000,
    },
    "o3-mini": {
        "name": "o3-mini",
        "display_name": "o3 Mini",
        "provider": "openai",
        "max_tokens": 100000,
        "context_window": 200000,
    },
}

# Available Models via GitHub Copilot API
# Updated: 2026-04-24 (ref: docs.github.com/en/copilot/reference/ai-models/supported-models)
COPILOT_MODELS = {
    # OpenAI Models — GPT-5.5 family
    "gpt-5.5": {
        "name": "gpt-5.5",
        "display_name": "GPT-5.5",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 1000000,
    },
    # OpenAI Models — GPT-5.4 family (GA 2026-03-05 / 2026-03-17)
    "gpt-5.4": {
        "name": "gpt-5.4",
        "display_name": "GPT-5.4",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 1000000,
    },
    "gpt-5.4-mini": {
        "name": "gpt-5.4-mini",
        "display_name": "GPT-5.4 Mini",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,
    },
    # OpenAI Models — existing
    "gpt-5.3-codex": {
        "name": "gpt-5.3-codex",
        "display_name": "GPT-5.3 Codex",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 400000,

    },
    "gpt-5.3-codex-spark": {
        "name": "gpt-5.3-codex-spark",
        "display_name": "GPT-5.3 Codex Spark",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 128000,

    },
    "gpt-5.2-codex": {
        "name": "gpt-5.2-codex",
        "display_name": "GPT-5.2 Codex",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 400000,

    },
    "gpt-5.2": {
        "name": "gpt-5.2",
        "display_name": "GPT-5.2",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,

    },
    "gpt-5.1-codex": {
        "name": "gpt-5.1-codex",
        "display_name": "GPT-5.1 Codex",
        "provider": "openai",
        "api": "responses",
        "max_tokens": 128000,
        "context_window": 400000,

    },
    "gpt-5.1": {
        "name": "gpt-5.1",
        "display_name": "GPT-5.1",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,

    },
    "gpt-5": {
        "name": "gpt-5",
        "display_name": "GPT-5",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,

    },
    "gpt-5-mini": {
        "name": "gpt-5-mini",
        "display_name": "GPT-5 Mini",
        "provider": "openai",
        "max_tokens": 128000,
        "context_window": 400000,

    },
    # Anthropic Claude Models
    "claude-opus-4.7": {
        "name": "claude-opus-4.7",
        "display_name": "Claude Opus 4.7",
        "provider": "anthropic",
        "max_tokens": 128000,
        "context_window": 200000,

    },
    "claude-opus-4.6": {
        "name": "claude-opus-4.6",
        "display_name": "Claude Opus 4.6",
        "provider": "anthropic",
        "max_tokens": 128000,
        "context_window": 200000,

    },
    "claude-sonnet-4.6": {
        "name": "claude-sonnet-4.6",
        "display_name": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "max_tokens": 64000,
        "context_window": 200000,

    },
    "claude-haiku-4.5": {
        "name": "claude-haiku-4.5",
        "display_name": "Claude Haiku 4.5",
        "provider": "anthropic",
        "max_tokens": 64000,
        "context_window": 200000,

    },
    # Google Gemini Models
    "gemini-3.1-pro": {
        "name": "gemini-3.1-pro",
        "display_name": "Gemini 3.1 Pro",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-3-pro": {
        "name": "gemini-3-pro",
        "display_name": "Gemini 3 Pro",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-3-flash": {
        "name": "gemini-3-flash",
        "display_name": "Gemini 3 Flash",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
    "gemini-2.5-pro": {
        "name": "gemini-2.5-pro",
        "display_name": "Gemini 2.5 Pro",
        "provider": "google",
        "max_tokens": 65536,
        "context_window": 1048576,
    },
}

# Auth provider registry
AUTH_PROVIDERS = {
    "antigravity": {"name": "Antigravity (Google)", "models_dict": ANTIGRAVITY_MODELS},
    "openai": {"name": "OpenAI", "models_dict": OPENAI_MODELS},
    "copilot": {"name": "GitHub Copilot", "models_dict": COPILOT_MODELS},
}

# Rate Limit Configuration
RATE_LIMIT_RETRY_AFTER = 60  # Default retry after in seconds
MAX_RETRIES = 3

# Default LLM Model per provider
DEFAULT_LLM_MODEL = "gemini-3-pro-high"             # Antigravity
DEFAULT_COPILOT_MODEL = "claude-opus-4.7"           # GitHub Copilot
DEFAULT_OPENAI_MODEL = "gpt-5.5"                    # OpenAI (ChatGPT backend)
