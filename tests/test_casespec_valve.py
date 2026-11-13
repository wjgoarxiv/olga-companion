"""CaseSpec v2 fixed-opening valve."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from olga_companion import case_compiler, case_spec

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_valve.json"
VALVE_LINE = (
    'VALVE LABEL="VALVE_A", TIME=0 s, PIPE=PIPE_A, '
    "SECTIONBOUNDARY=5, DIAMETER=0.08 m, OPENING=1"
)


def _spec() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_valve_compiles_with_the_builder_section_boundary() -> None:
    raw = _spec()

    validated = case_spec.validate_case_spec(raw)
    compiled = case_compiler.compile_case_spec(raw)

    assert validated["valid"] is True
    assert compiled.validation.clean is True, compiled.validation.diagnostics
    text = compiled.text
    assert VALVE_LINE in text
    assert "EQUILIBRIUMMODEL" not in text
    assert "HYDROVALVE" not in text
    assert "DIAMETER=0.1 m" in text
    assert text.count("DIAMETER=0.08 m") == 1


def test_valve_missing_opening_is_rejected() -> None:
    raw = _spec()
    del raw["equipment"][0]["opening"]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["normalized"] is None
    assert result["errors"][0]["code"] != "unsupported_equipment"
    assert "opening" in result["errors"][0]["field"]


@pytest.mark.parametrize("kind", ["separator", "controller"])
def test_valve_is_the_only_equipment_kind(kind: str) -> None:
    raw = _spec()
    raw["equipment"] = [{"kind": kind, "label": "OTHER"}]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    issue = result["errors"][0]
    assert issue["code"] == "unsupported_equipment"
    assert issue["message"] == "Equipment is outside CaseSpec v2."
    assert issue["guidance"] == (
        f"{kind} equipment is not supported; use source, sink, junction, flowpath and pipe constructs."
    )
