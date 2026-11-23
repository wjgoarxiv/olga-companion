"""Path-private, bounded projection of untrusted diagnostic evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from .case_spec_validation import JsonValue
from .run_outputs import redact_log_paths

_ALLOWED_FIELDS = ("issue", "code", "message", "detail", "severity")
# A token with a slash or backslash is a path unless every piece of it is a unit,
# so "kg/s", "Sm3/Sm3" and "(kg*m)/s" stay while "../Users/x/case.genkey" is hidden.
_PATH_TOKEN = re.compile(r"[^\s,;=\"'\]\[{}]*[/\\][^\s,;=\"'\]\[{}]*")
_UNIT_ATOM = re.compile(
    r"(?:[kMGmµcd]{0,2}(?:g|m|s|Pa|W|J|N|L|l|mol|t)|[kM]{0,2}(?:Sm3|Nm3|scf|stb|bbl)|m3|ft[23]?|in|mi|lbm?|"
    r"psi[ag]?|bar[ag]?|atm|h|hr|d|day|min|K|C|F|°C|°F|°|%|rad|cP|Btu|ton|1)(?:\d|[²³])*",
    re.IGNORECASE,
)


def _is_unit(token: str) -> bool:
    if "\\" in token or token.startswith(("/", "~", ".")) or token.endswith("/"):
        return False
    pieces = [piece for piece in re.split(r"[/*·^()\-]", token.rstrip(".:")) if piece]
    return bool(pieces) and all(_UNIT_ATOM.fullmatch(piece) for piece in pieces)


def _redact_path(match: re.Match[str]) -> str:
    token = match.group(0)
    return token if _is_unit(token) else "[private-path]"


def _safe_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    redacted = redact_log_paths(value)
    return _PATH_TOKEN.sub(_redact_path, redacted)[:limit]


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
