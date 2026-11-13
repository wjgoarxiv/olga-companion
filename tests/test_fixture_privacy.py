"""Fixtures and docs carry no customer or project names from owner cases."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Names of owner projects, yards and engine parts that must stay out of the repository's
# test data and docs. Matched case-insensitively as whole words. Built from fragments so this
# file never carries the names itself.
FORBIDDEN = ("NS" + "Y", "JM" + "U", "TR" + "ION", "S.54" + "58", "S54" + "58", "e2e" + "_final", "FB" + "IV", "LG" + "IM")
_PATTERN = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(token) for token in FORBIDDEN) + r")(?![A-Za-z0-9])", re.I)
_TEXT = {".csv", ".json", ".genkey", ".md", ".txt", ".tab", ".mfl", ".py", ".key", ".inc"}


def _scanned() -> list[Path]:
    roots = [ROOT / "tests" / "fixtures", ROOT / "docs"]
    return [path for root in roots for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _TEXT]


def hits(paths: list[Path]) -> list[str]:
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        found.extend(f"{path.relative_to(ROOT)}: {match.group(0)}" for match in _PATTERN.finditer(text))
    return found


def test_fixtures_and_docs_carry_no_owner_names() -> None:
    assert hits(_scanned()) == []


@pytest.mark.parametrize("token", FORBIDDEN)
def test_the_guard_catches_each_name(tmp_path: Path, token: str) -> None:
    planted = tmp_path / "planted.csv"
    planted.write_text(f"flowpath,pipe\nLINE_{token.lower()} x,{token}\n", encoding="utf-8")
    assert hits_outside_root([planted]) != []


def hits_outside_root(paths: list[Path]) -> list[str]:
    return [match.group(0) for path in paths for match in _PATTERN.finditer(path.read_text(encoding="utf-8"))]
