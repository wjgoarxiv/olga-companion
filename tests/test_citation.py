"""The project is citable: CITATION.cff carries the Zenodo concept DOI and both READMEs have a cite section."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONCEPT_DOI = "10.5281/zenodo.24554046"
PAPER_DOI = "10.5281/zenodo.24554103"


def _field(text: str, key: str) -> str:
    match = re.search(rf"^{key}:\s*\"?([^\"\n]+)\"?\s*$", text, re.M)
    assert match, f"CITATION.cff has no top-level {key}"
    return match.group(1).strip()


def test_citation_cff_names_the_release_and_its_doi() -> None:
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert _field(text, "cff-version") == "1.2.0"
    assert _field(text, "title").startswith("OLGA Companion")
    assert _field(text, "version") == "0.1.32"
    assert _field(text, "doi") == CONCEPT_DOI
    assert _field(text, "repository-code") == "https://github.com/wjgoarxiv/olga-companion"
    assert _field(text, "license") == "Apache-2.0"
    assert re.search(r"^authors:\n\s+- family-names: \"?Go\"?\n\s+given-names: \"?Woojin\"?", text, re.M)
    assert PAPER_DOI in text


@pytest.mark.parametrize(("readme", "heading"), [("README.md", "Cite"), ("README.ko.md", "인용")])
def test_readme_has_a_cite_section_with_both_dois(readme: str, heading: str) -> None:
    text = (ROOT / readme).read_text(encoding="utf-8")
    match = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"{readme} has no '## {heading}' section"
    body = match.group(1)
    assert f"https://doi.org/{CONCEPT_DOI}" in body
    assert f"https://doi.org/{PAPER_DOI}" in body
    assert "CITATION.cff" in body
