"""Authentication and transport construction for preview provider clients."""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime

from .openai_auth import (
    refresh_openai_token,
    save_tokens as save_openai_tokens,
)
from .openai_responses_adapter import OpenAIResponsesApiClient
from .copilot_requests import (
    CHATGPT_BACKEND_ACCEPT,
    CHATGPT_BACKEND_ORIGINATOR,
    CHATGPT_BACKEND_USER_AGENT,
    COPILOT_CHAT_BASE_URL,
    COPILOT_EXTRA_HEADERS,
    OPENAI_PREVIEW_BASE_URL,
)

logger = logging.getLogger(__name__)


def _extract_chatgpt_account_id(access_token: str) -> str | None:
    """Extract the ChatGPT account id from an OAuth JWT when present."""
    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        return payload.get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — malformed JWT is optional
        return None


def _resolve_openai_access_token(tokens: dict) -> str:
    """Return a usable OpenAI token, refreshing it near expiry."""
    access_token = tokens.get("access_token", "")
    if not access_token:
        raise RuntimeError(  # noqa: GENERIC_ERR_OK — preserve public error
            "OpenAI tokens dict missing 'access_token' field"
        )

    expires_at = tokens.get("expires_at", "")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.timestamp() < time.time() + 60:
                refresh_token = tokens.get("refresh_token", "")
                if not refresh_token:
                    raise RuntimeError(  # noqa: GENERIC_ERR_OK — preserve public error
                        "OpenAI access token expired and no refresh_token available."
                    )
                logger.info("OpenAI token expired, refreshing...")
                new_tokens = refresh_openai_token(refresh_token)
                save_openai_tokens(new_tokens)
                access_token = new_tokens["access_token"]
        except RuntimeError:
            raise
        except (TypeError, ValueError, OSError) as exc:
            logger.warning("OpenAI token expiry check failed: %s", exc)
    return access_token


def chatgpt_backend_headers(
    access_token: str,
    account_id: str | None = None,
) -> dict[str, str]:
    headers = {
        "originator": CHATGPT_BACKEND_ORIGINATOR,
        "User-Agent": CHATGPT_BACKEND_USER_AGENT,
        "Accept": CHATGPT_BACKEND_ACCEPT,
    }
    resolved_account_id = account_id or _extract_chatgpt_account_id(access_token)
    if resolved_account_id:
        headers["ChatGPT-Account-ID"] = resolved_account_id
    return headers


def create_openai_responses_transport(
    access_token: str,
    extra_headers: dict[str, str],
) -> OpenAIResponsesApiClient:
    return OpenAIResponsesApiClient(
        base_url=OPENAI_PREVIEW_BASE_URL,
        access_token=access_token,
        extra_headers=extra_headers,
    )


def create_copilot_chat_transport(access_token: str):
    # Runtime import preserves the established adapter monkeypatch seam.
    from .openai_chat_adapter import OpenAIChatApiClient

    return OpenAIChatApiClient(
        base_url=COPILOT_CHAT_BASE_URL,
        access_token=access_token,
        extra_headers=COPILOT_EXTRA_HEADERS,
    )


def build_openai_agent_client_from_codex(
    *,
    model: str | None = None,
    variant: str | None = None,
) -> OpenAIResponsesApiClient:
    """Build the agent ApiClient from the Codex CLI's OAuth credentials."""
    from . import codex_oauth

    selected_model = model or codex_oauth.DEFAULT_MODEL
    config = codex_oauth.resolve_variant(
        selected_model,
        variant or codex_oauth.DEFAULT_VARIANT,
    )
    credentials = codex_oauth.get_fresh_credentials()
    access_token = credentials.access_token
    headers = chatgpt_backend_headers(access_token, credentials.account_id)
    reasoning = {
        "effort": config["reasoning.effort"],
        "summary": config["reasoning.summary"],
    }
    text = {"verbosity": config["text.verbosity"]}
    return OpenAIResponsesApiClient(
        base_url=OPENAI_PREVIEW_BASE_URL,
        access_token=access_token,
        extra_headers=headers,
        reasoning=reasoning,
        text=text,
    )
