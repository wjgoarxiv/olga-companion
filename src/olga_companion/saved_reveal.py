"""Allow-list of files the native save route has just written."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from pathlib import Path

from .config import project_root

_REVEAL_ID = re.compile(r"^[0-9a-f]{32}$")
_LOCK = threading.Lock()


def _store_path() -> Path:
    return project_root() / "var" / "saved-reveals.json"


def _load(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    loaded: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str) and _REVEAL_ID.fullmatch(key):
            loaded[key] = value
    return loaded


def record_saved(path: Path) -> str:
    """Remember one file the save route just published and return its reveal id."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("A saved reveal requires the file that was just written.")
    reveal_id = secrets.token_hex(16)
    with _LOCK:
        store = _store_path()
        store.parent.mkdir(parents=True, exist_ok=True)
        recorded = _load(store)
        recorded[reveal_id] = str(resolved)
        temporary = store.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(recorded, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(store)
    return reveal_id


def path_for_reveal(reveal_id: str) -> Path | None:
    """Return the just-saved file for this id, or nothing for any other string."""
    if not isinstance(reveal_id, str) or _REVEAL_ID.fullmatch(reveal_id) is None:
        return None
    with _LOCK:
        stored = _load(_store_path()).get(reveal_id)
    if stored is None or any(char in stored for char in ("\x00", "\n", "\r")):
        return None
    candidate = Path(stored)
    if not candidate.is_absolute():
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_file():
        return None
    if os.path.normcase(str(resolved)) != os.path.normcase(stored):
        return None
    return resolved
