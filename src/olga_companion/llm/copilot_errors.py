"""Provider error classification and best-effort runtime status updates."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _looks_like_auth_error(exc: BaseException) -> bool:
    """Return whether an exception represents a credential rejection."""
    for attr in ("status", "status_code", "code"):
        if getattr(exc, attr, None) in (401, 403):
            return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "(401)",
            "(403)",
            "authentication failed",
            "unauthorized",
            "forbidden",
            "invalid_grant",
            "token revoked",
            "invalid api key",
        )
    )


def _is_copilot_rate_limited(exc: BaseException) -> bool:
    """Return whether a Copilot failure is a transient per-model 429."""
    for attr in ("status", "status_code", "code"):
        if getattr(exc, attr, None) == 429:
            return True
    message = str(exc).lower()
    return any(
        marker in message for marker in ("(429)", "rate limit", "too many requests")
    )


def _is_copilot_model_unsupported(exc: BaseException) -> bool:
    """Return whether Copilot rejected the selected chat model."""
    message = str(exc).lower()
    if (
        "unsupported_api_for_model" in message
        or "not accessible via the /chat/completions" in message
    ):
        return True
    for attr in ("status", "status_code", "code"):
        if getattr(exc, attr, None) == 404:
            return True
    if "(404)" in message:
        return True
    return any(
        marker in message
        for marker in (
            "model not found",
            "model_not_found",
            "does not exist",
            "invalid model",
            "model_not_supported",
            "unknown model",
            "no access to model",
            "model is not supported",
            "unsupported model",
        )
    )


def _note_provider_outcome(
    provider: str,
    exc: BaseException | None,
) -> None:
    """Update the provider auth marker without affecting the request path."""
    try:
        from . import provider_runtime_status

        if exc is None:
            provider_runtime_status.clear(provider)
        elif _looks_like_auth_error(exc):
            provider_runtime_status.record_auth_failure(provider)
    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — status is best-effort
        logger.debug("Unable to update provider runtime status")


def note_copilot_unsupported_model(model: str) -> None:
    try:
        from . import provider_runtime_status

        provider_runtime_status.record_unsupported_model("copilot", model)
    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — status is best-effort
        logger.debug("Unable to record unsupported Copilot model")


def note_copilot_model_fallback(requested: str, used: str) -> None:
    try:
        from . import provider_runtime_status

        provider_runtime_status.record_model_fallback(
            "copilot",
            requested=requested,
            used=used,
        )
    except Exception:  # noqa: BROAD_EXCEPT_OK, BLE001 — status is best-effort
        logger.debug("Unable to record Copilot model fallback")
