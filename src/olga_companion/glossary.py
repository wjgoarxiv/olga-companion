"""Read-only OLGA glossary. Unknown terms are not guessed."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

GLOSSARY_PATH = Path(__file__).resolve().parent / "resources" / "olga_glossary.json"


@lru_cache(maxsize=1)
def entries() -> tuple[dict[str, Any], ...]:
    payload = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return tuple(payload)


def lookup(term: str | None = None) -> dict[str, Any]:
    """Return one exact term, or the full list when no term is given."""
    if term is None or not str(term).strip():
        return {"entries": list(entries())}
    key = str(term).strip().upper()
    for entry in entries():
        if entry["term"] == key:
            return {"found": True, "entry": entry}
    return {"found": False}
