"""Optional diagnostic fields stay out of the compiled file until the user sets them."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from olga_companion import case_compiler, case_spec
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.case_intake import api_case_spec_requirements
from olga_companion.case_spec import case_spec_inline_schema

FIXTURES = Path(__file__).parent / "fixtures"
OUTPUTS = FIXTURES / "casespec_outputs.json"
SOURCE = FIXTURES / "casespec_source_massflow.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_absent_diagnostic_fields_match_the_golden_bytes() -> None:
    pairs = (
        (OUTPUTS, FIXTURES / "casespec_outputs.golden.genkey"),
        (SOURCE, FIXTURES / "casespec_source_massflow.golden.genkey"),
    )
    for spec_path, golden_path in pairs:
        assert case_compiler.render_case_spec(_load(spec_path)) == golden_path.read_bytes()


def test_steady_state_false_without_initial_conditions_does_not_compile() -> None:
    raw = _load(OUTPUTS)
    raw["integration"]["steady_state"] = False

    with pytest.raises(ValidationError, match="steady_state_off_requires_initial_conditions"):
        case_compiler.compile_case_spec(raw)


def test_stated_timestep_bounds_replace_only_those_tokens() -> None:
    raw = _load(OUTPUTS)
    raw["integration"]["dt_start_s"] = 0.5
    raw["integration"]["min_dt_s"] = 0.01

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert "MINDT=0.01 s, STARTTIME=0 s, DTSTART=0.5 s" in text
    assert "MAXDT=" not in text


def test_pressure_node_fractions_are_emitted_on_both_ends() -> None:
    raw = _load(OUTPUTS)
    for node in raw["nodes"]:
        if node["kind"] == "sink":
            node["gas_fraction"] = 0.2
            node["total_water_fraction"] = 0.8

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text
    sink = text.split("TAG=SINK", 1)[1].split("ENDNETWORKCOMPONENT", 1)[0]
    inlet = text.split("TAG=SOURCE", 1)[1].split("ENDNETWORKCOMPONENT", 1)[0]

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert "GASFRACTION=0.2 -, TOTALWATERFRACTION=0.8 -, TIME=0 s" in sink
    assert "GASFRACTION=0.2 -, TOTALWATERFRACTION=0.4 -, TIME=0 s" in inlet


def test_massflow_series_replaces_the_single_point_parentheses() -> None:
    raw = _load(SOURCE)
    raw["massflow_sources"][0]["series"] = [
        {
            "time_s": 0,
            "mass_flow_kg_s": 0,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
        {
            "time_s": 5,
            "mass_flow_kg_s": 2,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
    ]

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert (
        "TIME=(0, 5) s, MASSFLOW=(0, 2) kg/s, TEMPERATURE=(15, 15) C, "
        "GASFRACTION=(0.1, 0.1) -, TOTALWATERFRACTION=(0.4, 0.4) -"
    ) in text
    assert "TIME=(0) s" not in text


def test_a_decreasing_massflow_series_is_rejected() -> None:
    raw = _load(SOURCE)
    raw["massflow_sources"][0]["series"] = [
        {
            "time_s": 5,
            "mass_flow_kg_s": 2,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
        {
            "time_s": 0,
            "mass_flow_kg_s": 0,
            "temperature_c": 15,
            "gas_fraction": 0.1,
            "total_water_fraction": 0.4,
        },
    ]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "source_series_not_increasing"


def test_a_missing_inlet_fraction_is_refused() -> None:
    raw = _load(OUTPUTS)
    for node in raw["nodes"]:
        if node["kind"] == "source":
            del node["total_water_fraction"]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "pressure_node_fractions_required"


def test_requirements_and_prompt_ask_for_the_diagnostic_fields_as_optional() -> None:
    by_key = {
        item["key"]: item
        for group in api_case_spec_requirements()["groups"]
        for item in group["items"]
    }
    schema = case_spec_inline_schema()
    integration = schema["properties"]["integration"]["properties"]
    source = schema["properties"]["massflow_sources"]["items"]["properties"]

    for key in (
        "time.steady_state",
        "time.dt_start_s",
        "time.min_dt_s",
        "boundary.massflow_series",
        "outputs.trend_positions",
    ):
        assert by_key[key]["required"] is False
    assert "steady_state" in integration
    assert "dt_start_s" in integration
    assert "min_dt_s" in integration
    assert "series" in source
    assert "trend_positions" in schema["properties"]
    assert "trend_positions" not in schema["required"]
    assert "steady_state" not in schema["properties"]["integration"]["required"]
    lowered = SYSTEM_PROMPT.lower()
    assert "optional diagnostic inputs" in lowered
    assert "leave each one unset" in lowered
    assert "trend_positions" in lowered
    assert "first and last section" in lowered


def test_absent_trend_positions_record_the_first_and_last_section() -> None:
    compiled = case_compiler.compile_case_spec(_load(OUTPUTS))
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert 'POSITION LABEL="POS_MAIN_1", PIPE=PIPE_A, SECTION=1' in text
    assert 'POSITION LABEL="POS_MAIN", PIPE=PIPE_A, SECTION=10' in text
    assert (
        "TRENDDATA POSITION=(POS_MAIN_1, POS_MAIN), "
        "VARIABLE=(GT, HOL, ID, PT, QLT, TM)"
    ) in text


def test_default_trend_uses_the_first_pipe_and_the_last_pipe() -> None:
    raw = _load(OUTPUTS)
    raw["flowpaths"][0]["pipes"] = [
        {
            "label": "PIPE_A",
            "centerline_m": [[0.0, 0.0, 0.0], [40.0, 0.0, 0.0]],
            "diameter_m": 0.1,
            "roughness_m": 5e-5,
            "sections": 2,
        },
        {
            "label": "PIPE_B",
            "centerline_m": [[40.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
            "diameter_m": 0.1,
            "roughness_m": 5e-5,
            "sections": 3,
        },
    ]

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert 'POSITION LABEL="POS_MAIN_1", PIPE=PIPE_A, SECTION=1' in text
    assert 'POSITION LABEL="POS_MAIN", PIPE=PIPE_B, SECTION=3' in text


def test_named_trend_positions_replace_the_default() -> None:
    raw = _load(OUTPUTS)
    raw["trend_positions"] = [
        {"label": "POS_END", "pipe": "PIPE_A", "section": 10},
        {"label": "POS_MID", "pipe": "PIPE_A", "section": 4},
    ]

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert 'POSITION LABEL="POS_MID", PIPE=PIPE_A, SECTION=4' in text
    assert 'POSITION LABEL="POS_END", PIPE=PIPE_A, SECTION=10' in text
    assert "POS_MAIN" not in text
    assert (
        "TRENDDATA POSITION=(POS_MID, POS_END), "
        "VARIABLE=(GT, HOL, ID, PT, QLT, TM)"
    ) in text


def test_a_trend_section_outside_the_pipe_is_rejected() -> None:
    raw = _load(OUTPUTS)
    raw["trend_positions"] = [{"label": "POS_MID", "pipe": "PIPE_A", "section": 11}]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_geometry"
