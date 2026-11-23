"""Per-boot session token guarding mutating localhost routes (T3).

The sidecar mints one random token at import; the UI fetches it once from a GET
route and echoes it on every POST. This stops other local processes (and CSRF-
shaped requests from a browsing context) from driving the paid-LLM, side-effectful
API. It is a localhost hardening measure, not user authentication.
"""
from __future__ import annotations

import secrets

_BOOT_TOKEN = secrets.token_urlsafe(32)


def boot_token() -> str:
    return _BOOT_TOKEN


def verify(token: str | None) -> bool:
    if not token:
        return False
    try:
        candidate = token.encode("ascii")
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(candidate, _BOOT_TOKEN.encode("ascii"))
