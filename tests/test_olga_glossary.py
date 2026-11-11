"""Shipped OLGA glossary stays sourced, exact, and non-guessing."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import importlib.util

from olga_companion import glossary, sidecar
from olga_companion.agent import tools

_spec = importlib.util.spec_from_file_location(
    "build_olga_glossary",
    Path(__file__).parents[1] / "scripts" / "build_olga_glossary.py",
)
_generator = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_generator)
build_entries = _generator.build_entries

SHIPPED = Path(glossary.GLOSSARY_PATH)


def test_every_shipped_entry_has_a_source_line() -> None:
    entries = json.loads(SHIPPED.read_text(encoding="utf-8"))
    assert entries
    for entry in entries:
        assert entry["term"]
        assert entry["kind"] in {"keyword", "parameter", "output_variable"}
        assert entry["meaning"]
        assert entry["source"]["file"]
        assert isinstance(entry["source"]["line"], int) and entry["source"]["line"] > 0


def test_unknown_term_is_not_guessed() -> None:
    assert glossary.lookup("NOT_A_REAL_OLGA_TERM") == {"found": False}
    assert tools.dispatch("olga_glossary", {"term": "NOT_A_REAL_OLGA_TERM"}) == {"found": False}
    response = TestClient(sidecar.app).get("/api/glossary", params={"term": "NOT_A_REAL_OLGA_TERM"})
    assert response.status_code == 200
    assert response.json() == {"found": False}


def test_generator_matches_the_shipped_json() -> None:
    assert build_entries() == json.loads(SHIPPED.read_text(encoding="utf-8"))
