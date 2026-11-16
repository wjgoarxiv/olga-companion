"""Glossary phase fractions follow the OLGA 2022.1 vendor definitions (mass, not volume).

A novice run on 2026-11-10 kept a 0.83 *volume* gas fraction because the glossary said
GASFRACTION was a volume fraction; OLGA reads it as a mass fraction, so the boundary would
have injected pure water. The vendor extract below is checked in from
OlgaExecutables/cfg/NODEkeyinfo.txt so the test runs without an OLGA install.
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

import json
from pathlib import Path

import pytest

from olga_companion import glossary

VENDOR = Path(__file__).parents[1] / "resources" / "olga-vendor" / "keyinfo-fractions.json"


def _vendor() -> list[dict]:
    return json.loads(VENDOR.read_text(encoding="utf-8"))


def test_vendor_extract_names_the_three_node_fractions() -> None:
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
