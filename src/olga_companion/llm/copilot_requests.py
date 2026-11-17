"""Request constants and payload shaping for preview provider clients."""

from __future__ import annotations

from .catalog import _COPILOT_ALLOWED_IDS as _COPILOT_OWNER_ALLOWED_IDS
from .protocol import fix_schema

_DEFAULT_USER_PROMPT = (
    "Generate the preview JSON now per the system instruction. "
    "Return only the JSON object, no surrounding prose."
)

# OpenAIResponsesApiClient appends /responses to this ChatGPT backend base.
OPENAI_PREVIEW_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_OPENAI_PREVIEW_MODEL = "gpt-6.1-sol"

# Canonical headers required by the chatgpt.com backend-api WAF.
CHATGPT_BACKEND_ORIGINATOR = "codex_cli_rs"
CHATGPT_BACKEND_USER_AGENT = "codex_cli_rs/0.0.0 (Unknown 0; unknown) unknown"
CHATGPT_BACKEND_ACCEPT = "text/event-stream"

# GitHub Copilot's OpenAI-compatible chat surface and required editor headers.
COPILOT_CHAT_BASE_URL = "https://api.individual.githubcopilot.com"
COPILOT_EXTRA_HEADERS: dict[str, str] = {
    "Editor-Version": "vscode/1.95.0",
    "Editor-Plugin-Version": "copilot/1.0.0",
    "Openai-Intent": "conversation-panel",
}

# Owner-approved fallbacks, intersected with the catalog allowlist at import.
_COPILOT_FALLBACK_PREFERENCE = (
    "claude-haiku-4.5",
    "gpt-5-mini",
    "gemini-3.1-pro-preview",
)
_COPILOT_CHAT_FALLBACK_MODELS = tuple(
    model
    for model in _COPILOT_FALLBACK_PREFERENCE
    if model in _COPILOT_OWNER_ALLOWED_IDS
)


def generation_config(
    max_output_tokens: int,
    temperature: float,
) -> dict[str, int | float]:
    return {
        "maxOutputTokens": max_output_tokens,
        "temperature": temperature,
    }


def copilot_models_to_try(requested_model: str) -> tuple[str, ...]:
    return (requested_model,) + tuple(
        model
        for model in _COPILOT_CHAT_FALLBACK_MODELS
        if model and model != requested_model
    )


def adapt_openai_tools(tools: list[dict] | None) -> list[dict]:
    """Convert flat Responses-style declarations to OpenAI chat tool specs."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.get("name"),
                "description": tool.get("description", "") or "",
                "parameters": fix_schema(
                    tool.get("parameters") or {"type": "object", "properties": {}}
                ),
            },
        }
        for tool in (tools or [])
        if tool.get("name")
    ]


def _strip_provider_prefix(model: str) -> str:
    """Convert a litellm ``provider/model`` id to the raw model name."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model
