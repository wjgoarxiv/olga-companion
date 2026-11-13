"""Per-provider runtime auth-failure registry (process-global, thread-safe).

Why this exists: ``account_providers.build_provider_readiness`` reports a provider
as connected from on-disk *credential presence* alone. That overclaims 연결됨 when
the credential is present but the provider rejects it at request time (a real 401 /
revoked subscription / expired-and-unrefreshable token). codex_oauth already tracks
this for the openai/codex path via its own ``_RUNTIME_AUTH_FAILURE_AT`` marker; this
module is the equivalent for providers that had no such signal — copilot, antigravity.

A request client records a failure when an auth error (401/403) is seen, and clears
it on the next success. The readiness builder consults ``failed(provider)`` so the
provider list agrees with what actually works. Markers are process-global and reset
on restart — same lifetime semantics as codex_oauth's marker.
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
# provider_id -> monotonic-ish timestamp of the last recorded auth failure.
_FAILED_AT: dict[str, float] = {}
# ④ — models the provider LISTS but the chat surface rejects at runtime (e.g. Copilot lists
# gemini-3.5-flash but /chat/completions returns 400 model_not_supported). Learned per provider so the
# catalog stops re-offering them and resolve_llm_selection can steer away.
_UNSUPPORTED_MODELS: dict[str, set[str]] = {}
# ④ — one-shot notice that a request silently fell back off the operator's chosen model, so the UI can
# lure them to 설정 to pick a working model. provider_id -> {"requested", "used"}.
_MODEL_FALLBACK: dict[str, dict[str, str]] = {}


def record_unsupported_model(provider: str, model: str) -> None:
    """Remember that `provider` rejected `model` at request time (model_not_supported)."""
    if not provider or not model:
        return
    with _LOCK:
        _UNSUPPORTED_MODELS.setdefault(provider, set()).add(model)


def unsupported_models(provider: str) -> set[str]:
    """The set of `provider` models the chat surface has rejected this session."""
    if not provider:
        return set()
    with _LOCK:
        return set(_UNSUPPORTED_MODELS.get(provider, set()))


def record_model_fallback(provider: str, *, requested: str, used: str) -> None:
    """Record that a request fell back from `requested` to `used` on `provider` (one-shot notice)."""
    if not provider or not requested or requested == used:
        return
    with _LOCK:
        _MODEL_FALLBACK[provider] = {"requested": requested, "used": used}


def pop_model_fallback(provider: str) -> dict[str, str] | None:
    """Consume + return the pending fallback notice for `provider`, or None."""
    if not provider:
        return None
    with _LOCK:
        notice = _MODEL_FALLBACK.pop(provider, None)
    if notice is None:
        return None
    return {"provider": provider, **notice}


def record_auth_failure(provider: str) -> None:
    """Mark `provider` as having failed authentication at request time."""
    if not provider:
        return
    with _LOCK:
        _FAILED_AT[provider] = time.time()


def clear(provider: str) -> None:
    """Clear a recorded failure for `provider` (call on a successful request)."""
    if not provider:
        return
    with _LOCK:
        _FAILED_AT.pop(provider, None)


def failed(provider: str) -> bool:
    """True when `provider` has an unresolved recorded runtime auth failure."""
    if not provider:
        return False
    with _LOCK:
        return provider in _FAILED_AT


def reset_all() -> None:
    """Drop every recorded failure / unsupported-model / fallback notice. Tests / full re-auth sweep."""
    with _LOCK:
        _FAILED_AT.clear()
        _UNSUPPORTED_MODELS.clear()
        _MODEL_FALLBACK.clear()
