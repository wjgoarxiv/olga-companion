"""Per-provider model catalog for the companion's "AI 공급자 연결" panel.

Single honest source of which models each AI provider actually offers, so the
Settings UI can show a model picker per provider and the dispatch layer
(src/llm_client_factory.py) can validate a selection before routing a request.

Design rules:
- OpenAI/Codex models come from `codex_oauth.SUPPORTED_MODELS` — the live
  ChatGPT-Codex account allowlist (NOT the broad antigravity/constants
  OPENAI_MODELS catalog, most of whose entries 400 on this account).
- Copilot / Antigravity models come from the static catalogs in
  `antigravity/constants.py` (the provider serves these via its own infra).
- Providers with no model catalog wired yet (anthropic, openrouter) report an
  empty list — the UI shows no picker until a backend exists (no fake options).
- Nothing here is fetched from a network; all catalogs are static facts.
"""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ModelCatalogEntry(TypedDict):
    """Operator-facing model metadata advertised by the sidecar."""

    id: str
    label: str
    tier: str
    reasoning_efforts: NotRequired[list[str]]
    default_effort: NotRequired[str]

# Friendly labels and tier hints for the current OpenAI/Codex catalog. Keyed by
# model id so the label stays correct if the allowlist changes.
_OPENAI_LABELS: dict[str, str] = {
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6-astra": "GPT-6 Astra",
    "gpt-6-sol": "GPT-6 Sol",
    "gpt-6-luna": "GPT-6 Luna",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-luna": "GPT-5.6 Luna",
}
_OPENAI_TIERS: dict[str, str] = {
    "gpt-6.1-sol": "balanced",
    "gpt-6-astra": "flagship",
    "gpt-6-sol": "balanced",
    "gpt-6-luna": "efficient",
    "gpt-5.6-sol": "flagship",
    "gpt-5.6-terra": "balanced",
    "gpt-5.6-luna": "efficient",
}


def _openai_models() -> list[ModelCatalogEntry]:
    from .codex_oauth import SUPPORTED_MODELS, default_variant, supported_variants

    out: list[ModelCatalogEntry] = []
    for mid in SUPPORTED_MODELS:
        out.append(
            {
                "id": mid,
                "label": _OPENAI_LABELS.get(mid, mid),
                "tier": _OPENAI_TIERS.get(mid, "standard"),
                "reasoning_efforts": list(supported_variants(mid)),
                "default_effort": default_variant(mid),
            }
        )
    return out


def _catalog_models(models_dict: dict[str, Any]) -> list[ModelCatalogEntry]:
    """Project a antigravity/constants models_dict into the panel shape."""
    out: list[ModelCatalogEntry] = []
    for mid, meta in models_dict.items():
        label = mid
        if isinstance(meta, dict):
            label = str(meta.get("display_name") or meta.get("name") or mid)
        out.append({"id": mid, "label": label, "tier": "standard"})
    return out


# GitHub Copilot's per-account /models endpoint serves many families, several of which the
# /chat/completions surface then rejects (400 model_not_supported) or that the owner does not want
# offered. Owner directive (2026-06-07, BINDING): the Copilot picker must offer EXACTLY these four
# models, in this order, with these display labels — nothing else, regardless of the live list.
# Default = GPT-5.4 mini. Mapping display→id confirmed against api.individual.githubcopilot.com/models.
# NOTE: the exact runtime acceptance of gpt-5.4-mini on the /chat/completions surface needs a LIVE
# Copilot call to confirm; if it 400s the fallback (see copilot_clients) re-routes to another
# allowlisted model and records a one-shot notice.
_COPILOT_ALLOWED: tuple[tuple[str, str], ...] = (
    ("gpt-5.4-mini", "GPT-5.4 mini (default)"),
    ("gpt-5-mini", "GPT-5 mini"),
    ("claude-haiku-4.5", "Claude Haiku 4.5"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro (Preview)"),
)
_COPILOT_ALLOWED_IDS: tuple[str, ...] = tuple(mid for mid, _ in _COPILOT_ALLOWED)
_COPILOT_ALLOWED_LABELS: dict[str, str] = {mid: label for mid, label in _COPILOT_ALLOWED}


def _copilot_models(*, cache_only: bool = False) -> list[ModelCatalogEntry]:
    from .copilot_auth import list_chat_models

    # ④ — the /models list includes models the /chat/completions surface rejects at runtime
    # (e.g. gemini-3.5-flash → 400 model_not_supported). Once learned, stop offering them so the
    # operator can't pick a model that will only fall back.
    try:
        from . import provider_runtime_status
        unsupported = provider_runtime_status.unsupported_models("copilot")
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — optional lookup is fail-soft
        unsupported = set()

    # The account actually serves these ids (intersect the live list with the owner allowlist so we
    # never offer a model the account can't reach — and never offer anything outside the four).
    served = {m["id"] for m in list_chat_models(cache_only=cache_only) if m.get("id")}
    out: list[ModelCatalogEntry] = []
    for mid in _COPILOT_ALLOWED_IDS:
        if mid not in served or mid in unsupported:
            continue
        out.append({
            "id": mid,
            "label": _COPILOT_ALLOWED_LABELS[mid],
            "tier": "picker",
        })
    return out


def _xai_models(*, cache_only: bool = False) -> list[ModelCatalogEntry]:
    # Live text-output list from api.x.ai/v1/language-models; ids are never hardcoded.
    from .xai_oauth import list_chat_models

    return list_chat_models(cache_only=cache_only)  # type: ignore[return-value]


def available_models(provider_id: str, *, cache_only: bool = False) -> list[ModelCatalogEntry]:
    """Return the list of {id, label, tier} a provider offers (possibly empty).

    `cache_only=True` makes the copilot catalog non-blocking (serve cached/stale, refresh in the
    background) — use it on hot status-poll paths. Never raises."""
    try:
        if provider_id == "openai":
            return _openai_models()
        if provider_id == "copilot":
            return _copilot_models(cache_only=cache_only)
        if provider_id == "xai":
            return _xai_models(cache_only=cache_only)
        if provider_id == "antigravity":
            from .antigravity.constants import AUTH_PROVIDERS

            info = AUTH_PROVIDERS.get(provider_id, {})
            models_dict = info.get("models_dict") if isinstance(info, dict) else None
            if isinstance(models_dict, dict):
                return _catalog_models(models_dict)
        if provider_id == "apikey":
            from .api_key_connections import catalog_entries

            return catalog_entries()
        return []
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — catalog status is fail-soft
        return []


def default_model(provider_id: str, *, cache_only: bool = False) -> str | None:
    """The provider's default model id, or None when it has no catalog."""
    try:
        if provider_id == "openai":
            from .codex_oauth import DEFAULT_MODEL

            return DEFAULT_MODEL
        if provider_id == "copilot":
            models = _copilot_models(cache_only=cache_only)
            ids = [m["id"] for m in models]
            if not ids:
                return None
            # Owner directive: default = GPT-5.4 mini. If the account doesn't serve it, fall to the
            # next allowlisted model that IS offered (allowlist order = preference order).
            for pref in _COPILOT_ALLOWED_IDS:
                if pref in ids:
                    return pref
            return ids[0]
        if provider_id == "xai":
            models = _xai_models(cache_only=cache_only)
            return models[0]["id"] if models else None
        if provider_id == "antigravity":
            from .antigravity import constants as c

            return getattr(c, "DEFAULT_LLM_MODEL", None)
        return None
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — default is a fail-soft UI hint
        return None


def is_valid_model(provider_id: str, model: str) -> bool:
    """True only when `model` is in the provider's catalog (honest gate)."""
    if not isinstance(model, str) or not model.strip():
        return False
    return any(m["id"] == model for m in available_models(provider_id))


# Providers with a real backend + catalog branch above. Their catalog may be
# momentarily empty (copilot reads its model list live), but the provider itself
# is still serviceable — so selection logic must NOT treat an empty catalog as
# "unknown provider" and silently re-route to the default.
_KNOWN_PROVIDERS = frozenset({"openai", "copilot", "antigravity", "xai", "apikey"})

# Backend order for the Settings panel and the no-saved-selection default.
# anthropic / openrouter have no backend and are never listed.
PROVIDER_ORDER: tuple[str, ...] = ("openai", "copilot", "antigravity", "xai", "apikey")


def provider_login(provider_id: str) -> str:
    """How the operator connects this provider: device flow, key panel, or outside."""
    if provider_id == "xai":
        return "xai_device"
    if provider_id == "apikey":
        return "apikey"
    return "external"


def is_connected(provider_id: str) -> bool:
    """True when the provider can answer right now, checked locally only.

    Reads credential files / local login state — never the network, never
    token values. Any failure (missing files, malformed state) is False."""
    try:
        if provider_id == "openai":
            from . import codex_oauth

            return codex_oauth.load_credentials() is not None
        if provider_id == "copilot":
            from . import copilot_auth

            return copilot_auth.load_tokens() is not None
        if provider_id == "antigravity":
            from .antigravity import token as ag_token

            return ag_token.load_tokens() is not None
        if provider_id == "xai":
            from . import xai_oauth

            return xai_oauth.login_status().get("state") == "connected"
        if provider_id == "apikey":
            from . import api_key_connections as keys

            return bool(keys.catalog_entries())
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — status is fail-soft
        return False
    return False


def is_known_provider(provider_id: str) -> bool:
    """True for a wired provider (has a backend), independent of whether its
    catalog is currently populated. Used to avoid degrading a chosen, connected
    provider to the default when its live catalog is transiently empty."""
    return provider_id in _KNOWN_PROVIDERS
