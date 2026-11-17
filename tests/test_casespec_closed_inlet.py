"""Closed inlet: mass flow in, pressure out. No invented boundary values."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from olga_companion import case_compiler, case_spec
from olga_companion.agent.runtime import SYSTEM_PROMPT

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_source_massflow.json"
CLOSED_LINE = 'PARAMETERS LABEL="SOURCE", TYPE=CLOSED, X=0 m, Y=0 m, Z=0 m'
SOURCE_LINE = (
    'SOURCE LABEL="FEED", POSITION="POS_FEED", TIME=(0) s, '
    "MASSFLOW=(1) kg/s, TEMPERATURE=(40) C, "
    "GASFRACTION=(0.25) -, TOTALWATERFRACTION=(0) -"
)


def _closed_inlet() -> dict:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    inlet = raw["nodes"][0]
    assert inlet["label"] == "SOURCE"
    inlet["kind"] = "closed"
    del inlet["pressure_pa"]
    del inlet["temperature_c"]
    del inlet["gas_fraction"]
    del inlet["total_water_fraction"]
    return raw


def test_closed_inlet_compiles_with_massflow_source_and_pressure_outlet() -> None:
    raw = _closed_inlet()

    validated = case_spec.validate_case_spec(raw)
    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text
    inlet = text.split("TAG=SOURCE", 1)[1].split("ENDNETWORKCOMPONENT", 1)[0]

    assert validated["valid"] is True
    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert CLOSED_LINE in text
    assert SOURCE_LINE in text
    assert "PRESSURE=" not in inlet
    assert "TEMPERATURE=" not in inlet
    assert "TYPE=PRESSURE" in text.split("TAG=SINK", 1)[1]


def test_closed_inlet_without_massflow_is_rejected() -> None:
    raw = _closed_inlet()
    del raw["massflow_sources"]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert any(error["code"] == "closed_node_without_inflow" for error in result["errors"])


@pytest.mark.parametrize("field", ["pressure_pa", "temperature_c"])
def test_closed_inlet_rejects_pressure_or_temperature(field: str) -> None:
    raw = _closed_inlet()
    raw["nodes"][0][field] = 1_000_000.0 if field == "pressure_pa" else 20.0

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["normalized"] is None
    assert any(field in error["field"] for error in result["errors"])


def test_prompt_asks_which_inlet_and_does_not_pick() -> None:
    prompt = SYSTEM_PROMPT.lower()

    assert "pressure boundary" in prompt
    assert "closed end" in prompt
    assert "never pick" in prompt
