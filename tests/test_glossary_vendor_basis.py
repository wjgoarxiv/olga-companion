"""Glossary phase fractions follow the OLGA 2022.1 vendor definitions (mass, not volume).

A novice run on 2026-11-10 kept a 0.83 *volume* gas fraction because the glossary said
GASFRACTION was a volume fraction; OLGA reads it as a mass fraction, so the boundary would
have injected pure water. The notes below are in our own words and cite the line of
OlgaExecutables/cfg/NODEkeyinfo.txt they describe, so the test runs without an OLGA install.
"""

from __future__ import annotations

import json as _json
from pathlib import Path as _Path


def test_vendor_units_carry_no_markdown() -> None:
    glossary = _json.loads(
        (_Path(__file__).parents[1] / "src" / "olga_companion" / "resources" / "olga_glossary.json").read_text(encoding="utf-8")
    )
    text = _json.dumps(glossary, ensure_ascii=False)
    assert "`-` (dimensionless)" not in text

import json  # noqa: E402 — this section's own imports
from pathlib import Path  # noqa: E402 — this section's own imports

import pytest  # noqa: E402 — this section's own imports

from olga_companion import glossary  # noqa: E402 — this section's own imports

VENDOR = Path(__file__).parents[1] / "resources" / "olga-key-notes" / "fractions.json"


def _vendor() -> list[dict]:
    return json.loads(VENDOR.read_text(encoding="utf-8"))


def test_the_notes_name_the_three_node_fractions() -> None:
    terms = {row["term"] for row in _vendor()}
    assert {"GASFRACTION", "WATERFRACTION", "TOTALWATERFRACTION"} <= terms


@pytest.mark.parametrize("term", ["GASFRACTION", "WATERFRACTION", "TOTALWATERFRACTION"])
def test_glossary_fraction_is_a_mass_fraction(term: str) -> None:
    found = glossary.lookup(term)
    assert found["found"] is True
    meaning = found["entry"]["meaning"].lower()
    assert "mass fraction" in meaning
    assert "volume" not in meaning


def test_every_vendor_entry_matches_the_glossary_basis() -> None:
    for row in _vendor():
        entry = glossary.lookup(row["term"])["entry"]
        assert entry["meaning"] == row["meaning"]
        assert entry["source"] == {"file": row["file"], "line": row["line"]}


def test_the_fraction_notes_keep_the_meaning_a_user_needs() -> None:
    gas = glossary.lookup("GASFRACTION")["entry"]["meaning"]
    assert "-1" in gas and "PVT table" in gas and "gas and oil" in gas
    free = glossary.lookup("WATERFRACTION")["entry"]["meaning"]
    total = glossary.lookup("TOTALWATERFRACTION")["entry"]["meaning"]
    assert "free water" in free and "TOTALWATERFRACTION" in free
    assert "-1" in total and "WATERFRACTION" in total
