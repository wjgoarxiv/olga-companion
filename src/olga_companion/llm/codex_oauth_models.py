"""Credential and model value objects shared by the Codex OAuth modules."""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import Callable
from typing import Any


CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_ENDPOINT = "https://auth.openai.com/oauth/authorize"
TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
REDIRECT_PORT = 1455
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/auth/callback"
OAUTH_SCOPES = "openid profile email offline_access"
RESPONSES_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"
REFRESH_WINDOW_SECONDS = 5 * 60

MODEL_VARIANTS: dict[str, tuple[str, ...]] = {
    "gpt-6.1-sol": ("max", "xhigh", "high", "medium", "low"),
    "gpt-6-astra": ("max", "xhigh", "high", "medium", "low"),
    "gpt-6-sol": ("max", "xhigh", "high", "medium", "low"),
    "gpt-6-luna": ("max", "xhigh", "high", "medium", "low"),
    "gpt-5.6-sol": ("max", "xhigh", "high", "medium", "low"),
    "gpt-5.6-terra": ("max", "xhigh", "high", "medium", "low"),
    "gpt-5.6-luna": ("max", "xhigh", "high", "medium", "low"),
}
SUPPORTED_MODELS = tuple(MODEL_VARIANTS)
SUPPORTED_VARIANTS = ("max", "xhigh", "high", "medium", "low")

_VARIANT_PROFILE: dict[str, dict[str, str]] = {
    "max": {"effort": "max", "summary": "detailed", "verbosity": "high"},
    "xhigh": {"effort": "xhigh", "summary": "detailed", "verbosity": "high"},
    "high": {"effort": "high", "summary": "detailed", "verbosity": "high"},
    "medium": {"effort": "medium", "summary": "auto", "verbosity": "medium"},
    "low": {"effort": "low", "summary": "auto", "verbosity": "low"},
}

VARIANTS: dict[tuple[str, str], dict[str, str]] = {
    (model, variant): {
        "reasoning.effort": profile["effort"],
        "reasoning.summary": profile["summary"],
        "text.verbosity": profile["verbosity"],
    }
    for model, variants in MODEL_VARIANTS.items()
    for variant in variants
    for profile in (_VARIANT_PROFILE[variant],)
}

DEFAULT_MODEL = "gpt-6.1-sol"
DEFAULT_VARIANT = "medium"
MODEL_DEFAULT_VARIANTS = {model: DEFAULT_VARIANT for model in SUPPORTED_MODELS}

_CODEX_MODEL_NOT_FOUND_CODES = ("model_not_found", "model_not_supported")
_CODEX_MODEL_NOT_FOUND_MARKERS = (
    "model is not supported",
    "not supported when using codex",
    "unknown model",
    "does not exist",
)
_CODEX_400_TOKENS = ("(400)", "error 400", "http 400", "status=400", "status 400")


def codex_models_to_try(requested: str) -> tuple[str, ...]:
    """Retry order for one fallback: the requested model, then catalog order."""
    return (requested,) + tuple(model for model in SUPPORTED_MODELS if model != requested)


def is_codex_model_not_found(exc: BaseException, model: str = "") -> bool:
    """True when the Codex backend rejected the model itself with a 400.

    Code markers stand alone; any other marker also requires the rejected
    model id in the message, so an unrelated 400 (missing response/item,
    bad schema) never poisons the account's unavailable list.
    """
    for attr in ("status", "status_code", "code"):
        if getattr(exc, attr, None) == 400:
            break
    else:
        text = str(exc).lower()
        if not any(token in text for token in _CODEX_400_TOKENS):
            return False
    text = str(exc).lower()
    if any(marker in text for marker in _CODEX_MODEL_NOT_FOUND_CODES):
        return True
    if not model:
        return False
    return model.lower() in text and any(
        marker in text for marker in _CODEX_MODEL_NOT_FOUND_MARKERS
    )


class CodexAuthError(Exception):
    """Operator-safe Codex OAuth failure with a typed relogin signal."""

    def __init__(self, message: str, *, relogin_required: bool = False) -> None:
        super().__init__(message)
        self.relogin_required = relogin_required


def supported_variants(model: str) -> tuple[str, ...]:
    """Return the sendable Codex reasoning efforts for ``model``."""
    return MODEL_VARIANTS.get(model, ())


def default_variant(model: str) -> str:
    """Return the app's balanced fallback for a supported model."""
    return MODEL_DEFAULT_VARIANTS.get(model, DEFAULT_VARIANT)


def resolve_variant(model: str, variant: str) -> dict[str, str]:
    """Resolve a model/effort pair or raise an operator-safe error."""
    key = (model, variant)
    if key not in VARIANTS:
        raise CodexAuthError(
            f"지원하지 않는 모델/변형입니다: model={model!r} variant={variant!r}"
        )
    return dict(VARIANTS[key])


def b64url_decode(segment: str) -> bytes:
    """Base64url-decode a JWT segment, restoring missing padding."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_jwt_payload(
    token: str,
    *,
    decode_segment: Callable[[str], bytes] = b64url_decode,
) -> dict[str, Any]:
    """Decode a trusted local JWT payload without verifying its signature."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = json.loads(decode_segment(parts[1]))
    except (
        AttributeError,
        RecursionError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        return {}
    return payload if isinstance(payload, dict) else {}


def jwt_expiry(
    token: str,
    *,
    decode_payload: Callable[[str], dict[str, Any]] = decode_jwt_payload,
) -> float | None:
    """Return the JWT ``exp`` claim as a POSIX timestamp, when present."""
    exp = decode_payload(token).get("exp")
    if isinstance(exp, (int, float)):
        return float(exp)
    return None


def account_id_from_id_token(
    id_token: str,
    *,
    decode_payload: Callable[[str], dict[str, Any]] = decode_jwt_payload,
) -> str | None:
    """Extract ``chatgpt_account_id`` from an OpenAI JWT."""
    auth_claim = decode_payload(id_token).get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        account_id = auth_claim.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def mask_account_id(account_id: str | None) -> str | None:
    """Mask an account id for operator-visible status payloads."""
    if not account_id or not isinstance(account_id, str):
        return None
    if len(account_id) <= 4:
        return "****"
    return "****" + account_id[-4:]


def _facade_helper(name: str, fallback: Callable[..., Any]) -> Callable[..., Any]:
    """Resolve legacy helper rebinding without coupling import initialization."""
    from . import codex_oauth

    return getattr(codex_oauth, name, fallback)


class CodexCredentials:
    """In-memory secrets; repr intentionally exposes only source and masked id."""

    __slots__ = ("access_token", "refresh_token", "id_token", "account_id", "source")

    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: str,
        id_token: str = "",
        account_id: str | None = None,
        source: str,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.id_token = id_token
        self.account_id = account_id
        self.source = source

    def __repr__(self) -> str:
        mask = _facade_helper("_mask_account_id", mask_account_id)
        return (
            f"CodexCredentials(source={self.source!r}, "
            f"account_id={mask(self.account_id)!r})"
        )

    @property
    def expires_at(self) -> float | None:
        """POSIX timestamp the access token expires at, when known."""
        expiry = _facade_helper("_jwt_expiry", jwt_expiry)
        return expiry(self.access_token)

    def is_expiring(self, *, window: float = REFRESH_WINDOW_SECONDS) -> bool:
        """Return whether this credential must be refreshed before use."""
        exp = self.expires_at
        if exp is None:
            return True
        return (exp - time.time()) < window
