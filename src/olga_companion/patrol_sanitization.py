"""Path-private, bounded projection of untrusted diagnostic evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from .case_spec_validation import JsonValue
from .run_outputs import redact_log_paths

_ALLOWED_FIELDS = ("issue", "code", "message", "detail", "severity")
_PRIVATE_PATH = re.compile(r"(?:(?:[A-Za-z]:\\|/)[^\s,;\"'\]\[{}]+)")


def _safe_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    redacted = redact_log_paths(value)
    return _PRIVATE_PATH.sub("[private-path]", redacted)[:limit]


def safe_diagnostic_text(value: Any, limit: int) -> str:
    return _safe_text(value, limit) or ""


def bounded_diagnostic_items(value: JsonValue | None, limit: int) -> list[JsonValue]:
    if not isinstance(value, list):
        return []
    bounded: list[JsonValue] = []
    for item in value[:8]:
        if isinstance(item, dict):
            public = {
                key: safe
                for key in _ALLOWED_FIELDS
                if (safe := _safe_text(item.get(key), limit)) is not None
            }
            encoded = json.dumps(public, ensure_ascii=False, sort_keys=True)
        else:
            encoded = _safe_text(item, limit) or "unavailable"
        bounded.append(encoded[:limit])
    return bounded
