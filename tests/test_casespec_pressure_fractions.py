"""PRESSURE boundaries require user-stated gas and total-water fractions."""
from __future__ import annotations

import json
from pathlib import Path

from olga_companion import case_compiler, case_spec
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.case_intake import api_case_spec_requirements
from olga_companion.case_spec_recovery import recover_case_spec

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_outputs.json"
SAMPLE_SOURCE = {"gas_fraction": 0.2, "total_water_fraction": 0.4}
SAMPLE_SINK = {"gas_fraction": 0.15, "total_water_fraction": 0.35}


def _spec() -> dict:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for node in raw["nodes"]:
        if node["kind"] == "source":
            node.update(SAMPLE_SOURCE)
        elif node["kind"] == "sink":
            node.update(SAMPLE_SINK)
    return raw


def test_missing_sink_gas_fraction_is_refused() -> None:
    raw = _spec()
    for node in raw["nodes"]:
        if node["kind"] == "sink":
            del node["gas_fraction"]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["publishable"] is False
    assert result["errors"][0]["code"] == "pressure_node_fractions_required"


def test_missing_inlet_water_fraction_is_refused() -> None:
    raw = _spec()
    for node in raw["nodes"]:
        if node["kind"] == "source":
            del node["total_water_fraction"]

    result = case_spec.validate_case_spec(raw)

    assert result["errors"][0]["code"] == "pressure_node_fractions_required"


def test_closed_inlet_does_not_require_node_fractions() -> None:
    raw = _spec()
    for node in raw["nodes"]:
        if node["kind"] == "source":
            node.clear()
            node.update({"label": "SOURCE", "kind": "closed"})
    raw["massflow_sources"] = [{
        "label": "FEED",
        "flowpath": "MAIN",
        "pipe": "PIPE_A",
        "section": 1,
        "time_s": 0.0,
        "mass_flow_kg_s": 1.0,
        "temperature_c": 15.0,
        "gas_fraction": 0.0,
        "total_water_fraction": 1.0,
    }]

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is True


def test_compiler_emits_both_fractions_on_every_pressure_node() -> None:
    compiled = case_compiler.compile_case_spec(_spec())
    text = compiled.text
    inlet = text.split("TAG=SOURCE", 1)[1].split("ENDNETWORKCOMPONENT", 1)[0]
    outlet = text.split("TAG=SINK", 1)[1].split("ENDNETWORKCOMPONENT", 1)[0]

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert compiled.validation.validator_clean is True
    assert "GASFRACTION=0.2 -, TOTALWATERFRACTION=0.4 -, TIME=0 s" in inlet
    assert "GASFRACTION=0.15 -, TOTALWATERFRACTION=0.35 -, TIME=0 s" in outlet


def test_requirements_mark_pressure_fractions_required() -> None:
    by_key = {
        item["key"]: item
        for group in api_case_spec_requirements()["groups"]
        for item in group["items"]
    }

    for key in (
        "boundary.source_gas_fraction",
        "boundary.source_total_water_fraction",
        "boundary.sink_gas_fraction",
        "boundary.sink_total_water_fraction",
    ):
        assert by_key[key]["required"] is True
    assert by_key["boundary.sink_gas_fraction"]["label"] == "출구 유체 조성: 기체 분율, 총 물 분율"
    assert "총 물 분율" in by_key["boundary.sink_total_water_fraction"]["label"]
    assert "입구 유체 조성" in by_key["boundary.source_gas_fraction"]["label"]


def test_prompt_asks_the_beginner_and_does_not_fill_fractions() -> None:
    prompt = SYSTEM_PROMPT

    assert "출구로 나가는 유체가 물뿐이면 기체 0, 물 1" in prompt
    assert "never fill" in prompt.lower()


def test_pressure_fractions_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "case.genkey"
    original = case_compiler.render_case_spec(_spec())
    source.write_bytes(original)

    recovered = recover_case_spec(source)
    inlet = next(node for node in recovered.nodes if node.kind == "source")
    outlet = next(node for node in recovered.nodes if node.kind == "sink")

    assert case_compiler.render_case_spec(recovered) == original
    assert inlet.gas_fraction == 0.2
    assert inlet.total_water_fraction == 0.4
    assert outlet.gas_fraction == 0.15
    assert outlet.total_water_fraction == 0.35
