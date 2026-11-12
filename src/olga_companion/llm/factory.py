"""Lane 2 — unified per-provider LLM client factory + selection resolver.

The sidecar's in-app LLM flows (intent, ai-session answer, create preview /
multi-agent designer & reviewer) all consume a *simple text client* with the
shape `(*, system_prompt, user_prompt) -> str`. Historically every call site
built a codex client directly, so the app was OpenAI-only in practice.

This module routes that same client shape to the operator's chosen provider:
- openai     → codex_oauth.build_codex_llm_client (unchanged path)
- antigravity→ copilot_clients.AntigravityPreviewClient (Gemini)
- copilot    → copilot_clients.CopilotPreviewClient (GitHub Copilot)
- xai        → xai_oauth.build_text_client (Responses API at api.x.ai)

`resolve_llm_selection` decides (provider, model, variant) from, in priority:
per-request headers → the operator's saved settings → the openai/default. So
with no header and no saved preference, it returns ("openai", DEFAULT_MODEL,
"medium") and the codex path is taken verbatim — codex regression is zero.

Tool-calling agent paths: the web librarian stays codex-specific, but the
current-file deep agent is now PROVIDER-AWARE — it routes to codex (openai) or
CopilotPreviewClient.generate_with_tools (copilot) via
the T2 agent runtime. This module
still serves only the simple text-client shape; the tool loop lives there.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

# The simple text client contract shared by every provider here.
TextClient = Callable[..., str]

_VALID_VARIANTS = ("xhigh", "high", "medium", "low")


def default_connected_selection() -> tuple[str, str, str] | None:
    """First connected provider in panel order with its default model.

    Local checks only (no network). apikey resolves to the first verified
    connection id. None when no provider is connected."""
    from . import catalog as model_catalog

    for name in model_catalog.PROVIDER_ORDER:
        if not model_catalog.is_connected(name):
            continue
        if name == "apikey":
            from . import api_key_connections as keys

            entries = keys.catalog_entries()
            if not entries:
                continue
            return (name, entries[0]["id"], "medium")
        model = model_catalog.default_model(name, cache_only=True) or ""
        if name == "openai":
            from . import codex_oauth

            variant = codex_oauth.default_variant(model)
        else:
            variant = "medium"
        return (name, model, variant)
    return None


def resolve_llm_selection(
    headers: Mapping[str, str] | None,
    settings: Mapping[str, Any] | None,
    *,
    default_provider: str = "openai",
) -> tuple[str, str, str]:
    """Resolve (provider, model, variant) from headers, then saved settings,
    then the first connected provider (or the openai/default fallback when
    none is connected). A saved selection is kept as-is even when its
    provider is currently disconnected. `headers` keys are matched
    case-insensitively (x-llm-provider / x-llm-model / x-llm-variant)."""
    from . import catalog as model_catalog

    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    settings = settings or {}

    h_provider = str(h.get("x-llm-provider") or "").strip().lower()
    h_model = str(h.get("x-llm-model") or "").strip()
    h_variant = str(h.get("x-llm-variant") or "").strip().lower()

    saved_provider = str(settings.get("active_llm_provider") or "").strip()
    connected_default: tuple[str, str, str] | None = None
    if not h_provider and not saved_provider:
        connected_default = default_connected_selection()
    provider = (
        h_provider
        or saved_provider
        or (connected_default[0] if connected_default else default_provider)
    )
    # An UNKNOWN provider (no backend) can't be honoured → fall back to default. But a KNOWN provider
    # whose live catalog is momentarily empty (copilot reads its models over the network) keeps its
    # identity — else a transient empty catalog silently re-routes the operator's chosen provider to
    # codex, which then 401s and surfaces as a misleading "공급자 응답 실패".
    if not model_catalog.available_models(provider) and not model_catalog.is_known_provider(provider):
        provider = default_provider

    saved_models = settings.get("provider_models") or {}
    saved_model = saved_models.get(provider) if isinstance(saved_models, Mapping) else None
    if connected_default is not None:
        model = h_model or (saved_model or "") or connected_default[1]
    else:
        model = h_model or (saved_model or "") or (model_catalog.default_model(provider) or "")
    # Drop a model the resolved provider doesn't actually offer.
    if model and not model_catalog.is_valid_model(provider, model):
        model = model_catalog.default_model(provider) or ""

    variant = (
        h_variant
        or str(settings.get("active_llm_variant") or "").strip()
        or (connected_default[2] if connected_default else "medium")
    )
    if provider == "openai":
        from . import codex_oauth

        if variant not in codex_oauth.supported_variants(model):
            variant = codex_oauth.default_variant(model)
    elif variant not in _VALID_VARIANTS:
        variant = "medium"

    return provider, model, variant


def build_llm_client(
    provider: str, model: str, variant: str
) -> Optional[TextClient]:
    """Build the simple text client for the chosen provider, or None when the
    provider can't be served (no creds / unknown provider). Never raises."""
    try:
        if provider == "openai":
            from . import codex_oauth

            return codex_oauth.build_codex_llm_client(
                model=model or codex_oauth.DEFAULT_MODEL,
                variant=variant or codex_oauth.DEFAULT_VARIANT,
            )
        if provider == "antigravity":
            from .copilot_clients import AntigravityPreviewClient
            from . import catalog as model_catalog

            return AntigravityPreviewClient(
                model=model or (model_catalog.default_model("antigravity") or "")
            )
        if provider == "copilot":
            from .copilot_clients import CopilotPreviewClient
            from . import catalog as model_catalog

            # When the live catalog is momentarily empty, `model` and default_model can both be empty;
            # fall back to an owner-approved copilot model so the client is usable (not an empty model
            # that the chat API rejects) — keeps the request on copilot instead of dead-ending. The
            # owner allowlist's first entry (gpt-5.4-mini) is the directed default; never gpt-4o.
            chosen = model or (model_catalog.default_model("copilot") or "") or model_catalog._COPILOT_ALLOWED_IDS[0]
            return CopilotPreviewClient(model=chosen)
        if provider == "xai":
            from . import catalog as model_catalog
            from . import xai_oauth

            if xai_oauth.login_status()["state"] != "connected":
                return None
            return xai_oauth.build_text_client(model or (model_catalog.default_model("xai") or ""))
        if provider == "apikey":
            from .api_key_connections import build_agent_client

            return build_agent_client(model)
        logger.warning("build_llm_client: unknown provider %r", provider)
        return None
    except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — degrade to unavailable
        logger.warning("build_llm_client(%s) unavailable: %s", provider, exc)
        return None
