"""CaseSpec v2 mass-flow SOURCE attachment."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from olga_companion import case_compiler, case_spec

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_source_massflow.json"
SOURCE_LINE = (
    'SOURCE LABEL="FEED", POSITION="POS_FEED", TIME=(0) s, '
    "MASSFLOW=(1) kg/s, TEMPERATURE=(40) C, "
    "GASFRACTION=(0.25) -, TOTALWATERFRACTION=(0) -"
)


def _spec() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_source_massflow_compiles_to_grounded_syntax_and_keeps_pressure_outlet() -> None:
    raw = _spec()

    validated = case_spec.validate_case_spec(raw)
    compiled = case_compiler.compile_case_spec(raw)

    assert validated["valid"] is True
    assert validated["normalized"]["massflow_sources"][0]["mass_flow_kg_s"] == 1.0
    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    text = compiled.text
    assert 'POSITION LABEL="POS_FEED", PIPE=PIPE_A, SECTION=1' in text
    assert SOURCE_LINE in text
    assert 'TAG=SINK' in text and "TYPE=PRESSURE" in text
    sink = text.split("TAG=SINK", 1)[1].split("ENDNETWORKCOMPONENT", 1)[0]
    assert "TYPE=PRESSURE" in sink
    assert "SOURCE" not in sink


def test_source_massflow_missing_temperature_is_rejected() -> None:
    raw = _spec()
    del raw["massflow_sources"][0]["temperature_c"]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_boundary"
    assert "temperature_c" in result["errors"][0]["field"]


def test_source_massflow_rejects_an_omitted_fraction_instead_of_defaulting() -> None:
    raw = _spec()
    del raw["massflow_sources"][0]["total_water_fraction"]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["normalized"] is None


def test_pressure_only_spec_stays_free_of_a_massflow_source() -> None:
    raw = _spec()
    del raw["massflow_sources"]

    validated = case_spec.validate_case_spec(raw)
    text = case_compiler.render_case_spec(deepcopy(raw)).decode()

    assert validated["valid"] is True
    assert "massflow_sources" not in validated["normalized"]
    assert "\nSOURCE " not in text and " SOURCE " not in text
