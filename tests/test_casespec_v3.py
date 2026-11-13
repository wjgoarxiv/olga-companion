"""CaseSpec v3: length/elevation pipes, graded sections, valve schedules, larger caps
and pass-through junctions.

The keyword shapes compiled here (PIPE LENGTH/ELEVATION with a non-uniform LSEGMENT,
VALVE TIME/OPENING lists, JUNCTIONNODE MIXTERM/FLOWTERM_1 with one flowpath on each
side, nodes and GEOMETRY without coordinates) appear in a hand-built owner case that
ran to a normal stop in OLGA 2022.1.0; a run of this compiler's own v3 output is a
separate installed-app check. v2 specs keep their v2 grammar and bytes.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from olga_companion import case_compiler, case_spec
from olga_companion.case_spec_recovery import recover_case_spec

VALVE_FIXTURE = Path(__file__).parent / "fixtures" / "casespec_valve.json"


def _pipe(label: str, length: float, elevation: float, sections: int = 4, **extra: Any) -> dict[str, Any]:
    return {
        "label": label, "length_m": length, "elevation_m": elevation,
        "diameter_m": 0.05, "roughness_m": 5e-5, "sections": sections, **extra,
    }


def _v3() -> dict[str, Any]:
    boundary = {"temperature_c": 40.0, "gas_fraction": 0.2, "total_water_fraction": 0.4}
    return {
        "version": "3",
        "nodes": [
            {"label": "INLET", "kind": "source", "pressure_pa": 2_000_000.0, **boundary},
            {"label": "PASS", "kind": "junction"},
            {"label": "SPLIT", "kind": "junction"},
            {"label": "OUT_A", "kind": "sink", "pressure_pa": 1_000_000.0, **boundary},
            {"label": "OUT_B", "kind": "sink", "pressure_pa": 1_000_000.0, **boundary},
        ],
        "flowpaths": [
            {"label": "FP_A", "from": "INLET", "to": "PASS", "pipes": [_pipe("PA_1", 10.0, 0.0), _pipe("PA_2", 4.0, -1.0)]},
            {"label": "FP_B", "from": "PASS", "to": "SPLIT", "pipes": [_pipe("PB_1", 6.0, 2.0)]},
            {"label": "FP_C", "from": "SPLIT", "to": "OUT_A", "pipes": [_pipe("PC_1", 8.0, 0.0)]},
            {"label": "FP_D", "from": "SPLIT", "to": "OUT_B", "pipes": [_pipe("PD_1", 8.0, 0.5)]},
        ],
        "pvt_reference": "fluid.tab",
        "fluid_label": "TEST_FLUID",
        "thermal": {"model": "adiabatic"},
        "integration": {"end_time_s": 600.0},
        "outputs": ["PT", "TM"],
    }


def _valve(label: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "valve", "label": label, "flowpath": "FP_C", "pipe": "PC_1",
        "position": 0.5, "diameter_m": 0.04, "opening": 1.0, **extra,
    }


def _codes(raw: dict[str, Any]) -> list[str]:
    result = case_spec.validate_case_spec(raw)
    assert result["valid"] is False
    return [issue["code"] for issue in result["errors"]]


def test_length_elevation_network_compiles_without_coordinates() -> None:
    compiled = case_compiler.compile_case_spec(_v3())

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    text = compiled.text
    assert text.splitlines()[0] == case_compiler.PROVENANCE_MARKER_V3
    assert "LENGTH=10 m, ELEVATION=0 m" in text
    assert "LENGTH=4 m, ELEVATION=-1 m" in text
    for absent in ("XEND", "XSTART", " X=", "ZEND"):
        assert absent not in text
    assert ' GEOMETRY LABEL="G-FP_A"\n' in text


def test_pass_through_junction_uses_mixterm_in_and_flowterm_out() -> None:
    text = case_compiler.compile_case_spec(_v3()).text

    assert "CONNECTION TERMINALS = (PASS MIXTERM, FP_A OUTLET)" in text
    assert "CONNECTION TERMINALS = (PASS FLOWTERM_1, FP_B INLET)" in text


def _as_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """The same network as straight centerline pipes on the x axis, version 2."""
    v2 = deepcopy(raw)
    v2["version"] = "2"
    starts = {"FP_A": 0.0, "FP_B": 14.0, "FP_C": 20.0, "FP_D": 20.0}
    for flowpath in v2["flowpaths"]:
        x = starts[flowpath["label"]]
        lane = 1.0 if flowpath["label"] == "FP_D" else 0.0
        for pipe in flowpath["pipes"]:
            length = pipe.pop("length_m")
            pipe.pop("elevation_m")
            pipe["centerline_m"] = [[x, 0.0, 0.0], [x + length, lane if x >= 20.0 else 0.0, 0.0]]
            x += length
    return v2


def test_the_v2_twin_is_otherwise_valid() -> None:
    v2 = _as_v2(_v3())
    v2["nodes"] = [node for node in v2["nodes"] if node["label"] != "PASS"]
    v2["flowpaths"] = [fp for fp in v2["flowpaths"] if fp["label"] != "FP_B"]
    v2["flowpaths"][0]["to"] = "SPLIT"
    v2["flowpaths"][0]["pipes"][-1]["centerline_m"][1] = [20.0, 0.0, 0.0]
    assert case_spec.validate_case_spec(v2)["valid"] is True, case_spec.validate_case_spec(v2)["errors"]


def test_pass_through_junction_stays_outside_v2() -> None:
    assert _codes(_as_v2(_v3())) == ["invalid_topology"]


def test_two_in_two_out_junction_is_still_refused_in_v3() -> None:
    raw = _v3()
    raw["nodes"].append({"label": "INLET_2", "kind": "source", "pressure_pa": 2_000_000.0,
                         "temperature_c": 40.0, "gas_fraction": 0.2, "total_water_fraction": 0.4})
    raw["flowpaths"].append({"label": "FP_E", "from": "INLET_2", "to": "SPLIT", "pipes": [_pipe("PE_1", 3.0, 0.0)]})
    assert "invalid_topology" in _codes(raw)


def test_parallel_flowpaths_between_two_junctions_are_not_a_cycle() -> None:
    raw = _v3()
    raw["nodes"].append({"label": "MERGE", "kind": "junction"})
    raw["flowpaths"][2]["to"] = "MERGE"
    raw["flowpaths"][3]["to"] = "MERGE"
    raw["nodes"] = [node for node in raw["nodes"] if node["label"] != "OUT_B"]
    raw["flowpaths"].append({"label": "FP_E", "from": "MERGE", "to": "OUT_A", "pipes": [_pipe("PE_1", 3.0, 0.0)]})
    assert case_spec.validate_case_spec(raw)["valid"] is True, case_spec.validate_case_spec(raw)["errors"]


def test_graded_segments_compile_in_the_given_order() -> None:
    raw = _v3()
    raw["flowpaths"][0]["pipes"][0] = _pipe("PA_1", 10.0, 0.0, sections=4, segment_lengths_m=[4.0, 3.0, 2.0, 1.0])

    text = case_compiler.compile_case_spec(raw).text

    assert "NSEGMENT=4, LSEGMENT=(4,3,2,1) m, LENGTH=10 m" in text


@pytest.mark.parametrize("lengths", [[4.0, 3.0, 2.0, 2.0], [5.0, 5.0]])
def test_graded_segments_must_match_the_pipe(lengths: list[float]) -> None:
    raw = _v3()
    raw["flowpaths"][0]["pipes"][0] = _pipe("PA_1", 10.0, 0.0, sections=4, segment_lengths_m=lengths)
    assert "invalid_geometry" in _codes(raw)


def test_valve_schedule_compiles_as_time_and_opening_lists() -> None:
    raw = _v3()
    raw["equipment"] = [_valve("V_1", schedule=[
        {"time_s": 0.0, "opening": 1.0}, {"time_s": 299.0, "opening": 1.0}, {"time_s": 300.0, "opening": 0.0},
    ])]

    text = case_compiler.compile_case_spec(raw).text

    assert 'VALVE LABEL="V_1", TIME=(0, 299, 300) s, PIPE=PC_1, SECTIONBOUNDARY=2, DIAMETER=0.04 m, OPENING=(1, 1, 0)' in text


@pytest.mark.parametrize("schedule", [
    [{"time_s": 0.0, "opening": 1.0}],
    [{"time_s": 0.0, "opening": 1.0}, {"time_s": 0.0, "opening": 0.0}],
    [{"time_s": 0.0, "opening": 1.0}, {"time_s": 5.0, "opening": 1.5}],
    [{"time_s": 0.0, "opening": 0.0}, {"time_s": 5.0, "opening": 1.0}],
])
def test_bad_valve_schedules_are_refused(schedule: list[dict[str, float]]) -> None:
    raw = _v3()
    raw["equipment"] = [_valve("V_1", schedule=schedule)]
    assert case_spec.validate_case_spec(raw)["valid"] is False


def test_v3_takes_more_than_sixteen_valves_up_to_256() -> None:
    raw = _v3()
    raw["flowpaths"][2]["pipes"][0]["sections"] = 300
    raw["equipment"] = [_valve(f"V_{index}", position=index / 300) for index in range(1, 18)]
    assert case_spec.validate_case_spec(raw)["valid"] is True
    raw["equipment"] = [_valve(f"V_{index}", position=index / 300) for index in range(1, 258)]
    assert case_spec.validate_case_spec(raw)["valid"] is False


def _v2_single() -> dict[str, Any]:
    raw = json.loads(VALVE_FIXTURE.read_text(encoding="utf-8"))
    raw["flowpaths"][0]["pipes"][0]["sections"] = 300
    return raw


def _v2_valve(index: int, **extra: Any) -> dict[str, Any]:
    return {"kind": "valve", "label": f"V_{index}", "flowpath": "MAIN", "pipe": "PIPE_A",
            "position": index / 300, "diameter_m": 0.08, "opening": 1.0, **extra}


def test_v2_takes_sixteen_valves_but_not_seventeen() -> None:
    raw = _v2_single()
    raw["equipment"] = [_v2_valve(index) for index in range(1, 17)]
    assert case_spec.validate_case_spec(raw)["valid"] is True
    raw["equipment"].append(_v2_valve(17))
    assert _codes(raw) == ["v2_item_limit"]


def test_v2_takes_thirty_two_sources_but_not_thirty_three() -> None:
    raw = _v2_single()
    raw.pop("equipment")
    source = {"flowpath": "MAIN", "pipe": "PIPE_A", "time_s": 0.0, "mass_flow_kg_s": 1.0,
              "temperature_c": 40.0, "gas_fraction": 0.2, "total_water_fraction": 0.4}
    raw["massflow_sources"] = [{"label": f"S_{index}", "section": index, **source} for index in range(1, 33)]
    assert case_spec.validate_case_spec(raw)["valid"] is True
    raw["massflow_sources"].append({"label": "S_33", "section": 33, **source})
    assert _codes(raw) == ["v2_item_limit"]


def test_v2_refuses_a_valve_schedule() -> None:
    raw = _v2_single()
    raw["equipment"] = [_v2_valve(1, schedule=[{"time_s": 0.0, "opening": 1.0}, {"time_s": 5.0, "opening": 0.0}])]
    assert _codes(raw) == ["unsupported_equipment"]


def test_v2_refuses_graded_sections() -> None:
    raw = _v2_single()
    raw["flowpaths"][0]["pipes"][0]["sections"] = 2
    raw["flowpaths"][0]["pipes"][0]["segment_lengths_m"] = [60.0, 40.0]
    raw.pop("equipment")
    assert _codes(raw) == ["invalid_geometry"]


def test_mixed_geometry_forms_are_refused() -> None:
    raw = _v3()
    raw["flowpaths"][1]["pipes"][0] = {
        "label": "PB_1", "centerline_m": [[0.0, 0.0, 0.0], [6.0, 0.0, 0.0]],
        "diameter_m": 0.05, "roughness_m": 5e-5, "sections": 4,
    }
    assert "invalid_geometry" in _codes(raw)


def test_reviewed_inputs_show_length_elevation_and_the_valve_schedule() -> None:
    from olga_companion.agent.approval_display import reviewed_inputs

    raw = _v3()
    raw["equipment"] = [_valve("V_1", schedule=[{"time_s": 0.0, "opening": 1.0}, {"time_s": 300.0, "opening": 0.0}])]
    rows = reviewed_inputs(case_spec.normalize_case_spec(raw), "en")
    names = [row["name"] for row in rows]

    assert "PA_1 Length" in names and "PA_1 Elevation change" in names
    assert "V_1 Schedule 2 Time" in names and "V_1 Schedule 2 Opening" in names


def test_an_elevation_offset_on_a_length_pipe_is_a_structured_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.case_transaction_models import TransactionFailure
    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    (tmp_path / "fluid.tab").write_text('PVTTABLE LABEL = "TEST_FLUID", PHASE = BOTH\n', encoding="utf-8")
    raw = _v3()
    result = plan_case_edits(
        raw,
        [{"op": "set_pipe_geometry", "flowpath": "FP_A", "pipe": "PA_1", "elevation_offset_m": 1.0}],
        expected_hash=case_spec_hash(raw),
        workspace_root=tmp_path,
    )
    assert isinstance(result, TransactionFailure)
    (issue,) = result.errors
    assert issue.code == "unsupported_operation"
    assert "length/elevation" in issue.message


def test_the_intake_card_keeps_the_pipe_path_required() -> None:
    from olga_companion.case_intake import api_case_spec_requirements

    groups = api_case_spec_requirements()["groups"]
    items = {item["key"]: item for group in groups for item in group["items"]}
    assert items["geometry.pipe_path"]["required"] is True


def test_v3_recovers_byte_exactly(tmp_path: Path) -> None:
    raw = _v3()
    raw["flowpaths"][0]["pipes"][0] = _pipe("PA_1", 10.0, 0.0, sections=4, segment_lengths_m=[4.0, 3.0, 2.0, 1.0])
    raw["equipment"] = [
        _valve("V_1", schedule=[{"time_s": 0.0, "opening": 1.0}, {"time_s": 300.0, "opening": 0.0}]),
        _valve("V_2", flowpath="FP_D", pipe="PD_1", opening=0.5),
    ]
    compiled = case_compiler.compile_case_spec(raw)
    source = tmp_path / "v3.genkey"
    source.write_bytes(compiled.compiled_bytes)

    recovered = recover_case_spec(source)

    assert case_compiler.render_case_spec(recovered) == compiled.compiled_bytes
    assert recovered.version == "3"
    pipe = recovered.flowpaths[0].pipes[0]
    assert (pipe.length_m, pipe.elevation_m, pipe.segment_lengths_m) == (10.0, 0.0, (4.0, 3.0, 2.0, 1.0))
    valves = {valve.label: valve for valve in recovered.equipment}
    assert [(point.time_s, point.opening) for point in valves["V_1"].schedule] == [(0.0, 1.0), (300.0, 0.0)]
    assert valves["V_2"].schedule is None and valves["V_2"].opening == 0.5


_INITIAL = {"pressure_pa": 100000.0, "temperature_c": 25.0, "void_fraction": 1.0}


def test_initial_conditions_go_with_steady_state_off_in_v3_only() -> None:
    raw = _v3()
    raw["initial_conditions"] = dict(_INITIAL)
    assert _codes(raw) == ["initial_conditions_need_steady_state_off"]
    raw["integration"]["steady_state"] = False
    assert case_spec.validate_case_spec(raw)["valid"] is True
    off = _v3()
    off["integration"]["steady_state"] = False
    assert _codes(off) == ["steady_state_off_requires_initial_conditions"]
    v2 = _as_v2(deepcopy(raw))
    assert "unsupported_initial_conditions" in _codes(v2)


def test_initial_conditions_compile_into_every_flowpath_and_recover(tmp_path: Path) -> None:
    raw = _v3()
    raw["initial_conditions"] = dict(_INITIAL)
    raw["integration"]["steady_state"] = False
    compiled = case_compiler.compile_case_spec(raw)
    lines = compiled.text.splitlines()
    flowpaths = sum(line.startswith("NETWORKCOMPONENT TYPE=FLOWPATH") for line in lines)
    assert lines.count(" INITIALCONDITIONS PRESSURE=100000 Pa, TEMPERATURE=25 C, VOIDFRACTION=1") == flowpaths
    source = tmp_path / "case.genkey"
    source.write_bytes(compiled.compiled_bytes)
    assert recover_case_spec(source) == case_spec.normalize_case_spec(raw)


def test_a_spec_without_initial_conditions_keeps_its_hash() -> None:
    from olga_companion.case_transactions import case_spec_hash

    spec = case_spec.normalize_case_spec(_v3())
    legacy = spec.model_dump_json(by_alias=True, exclude={"initial_conditions"}).encode("utf-8")
    import hashlib
    assert case_spec_hash(spec) == hashlib.sha256(legacy).hexdigest()
