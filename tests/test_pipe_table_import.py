"""A pipe table becomes a validated CaseSpec v3 network."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from olga_companion import case_compiler
from olga_companion.case_spec import normalize_case_spec
from olga_companion.case_spec_recovery import recover_case_spec
from olga_companion.pipe_table import read_table
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

TABLES = Path(__file__).parent / "fixtures" / "pipe_tables"
OPTIONS = ImportOptions(
    pvt_reference="fluid.tab", fluid_label="TEST_FLUID", thermal={"model": "adiabatic"},
    end_time_s=600.0, max_section_m=1.0,
)


def _import(name: str, options: ImportOptions = OPTIONS):
    return build_case_spec(read_table(TABLES / name), options)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pipes.csv"
    path.write_text(text, encoding="utf-8")
    return path


SMALL = (TABLES / "small_branch.csv").read_text(encoding="utf-8")


def test_small_table_compiles_with_the_table_topology() -> None:
    result = _import("small_branch.csv")

    assert result.issues == ()
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean, compiled.validation.diagnostics
    names = {label: source for source, label in result.label_map["flowpaths"].items()}
    edges = {(names[label], frm, to) for frm, to, label in compiled.topology_edges}
    nodes = {label: source for source, label in result.label_map["nodes"].items()}
    assert {(fp, nodes[a], nodes[b]) for fp, a, b in edges} == {
        ("FP_IN", "SRC", "J_1"), ("FP_A", "J_1", "OUT_A"), ("FP_B", "J_1", "OUT_B"),
    }
    assert 'VALVE LABEL="V_001", TIME=(0, 299, 300) s' in compiled.text


def test_synthetic_network_builds_compiles_and_stays_graded() -> None:
    result = _import("synthetic_network.csv")

    assert result.issues == (), result.issues[:5]
    summary = result.summary
    # The table has 319 flowpaths and 121 junctions; its two pass-through junctions are joined away.
    assert summary["flowpaths"] == 317 and summary["junctions"] == 119 and summary["valves"] == 66
    assert summary["worst_ratio_in_flowpaths"] <= 2.0
    assert summary["longest_section_m"] <= OPTIONS.max_section_m + 1e-9
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean, compiled.validation.diagnostics
    assert len(compiled.compiled_bytes) < case_compiler.MAX_COMPILED_BYTES
    assert "P008" not in " ".join(compiled.validation.diagnostics)
    assert compiled.section_count == summary["sections"] <= 5000


def test_valve_boundaries_land_where_the_valve_is() -> None:
    result = _import("small_branch.csv")
    spec = normalize_case_spec(result.spec)
    (valve,) = spec.equipment
    pipe = next(p for fp in spec.flowpaths for p in fp.pipes if p.label == valve.pipe)
    lengths = pipe.segment_lengths_m or (pipe.length / pipe.sections,) * pipe.sections
    boundary = max(1, int(valve.position * pipe.sections))
    assert abs(sum(lengths[:boundary]) - 0.5 * pipe.length) <= max(lengths)


def test_missing_diameter_is_a_row_issue(tmp_path: Path) -> None:
    text = SMALL.replace(",20.0,0.0,0.05,", ",20.0,0.0,,", 1)
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    assert any(issue.field == "inner_diameter_m" and issue.row == 5 for issue in result.issues)


def test_disconnected_table_is_refused(tmp_path: Path) -> None:
    text = SMALL + "FP_X,FP_X_P1,ISO_A,ISO_B,1.0,0.0,0.05,5e-05,,,,,,,,,,\n"
    text += ",,,,,,,,,,,,ISO_A,source,2.0,25.0,1.0,0.0\n,,,,,,,,,,,,ISO_B,sink,1.0,25.0,0.5,0.0\n"
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    assert any("connected" in issue.reason for issue in result.issues)


def test_a_two_in_two_out_node_is_refused_by_its_table_name(tmp_path: Path) -> None:
    text = SMALL + "FP_C,FP_C_P1,SRC2,J_1,3.0,0.0,0.05,5e-05,,,,,,,,,,\n"
    text += "FP_D,FP_D_P1,J_1,OUT_D,3.0,0.0,0.05,5e-05,,,,,,,,,,\n"
    text += ",,,,,,,,,,,,SRC2,source,5.0,25.0,1.0,0.0\n,,,,,,,,,,,,OUT_D,sink,1.0,25.0,0.5,0.0\n"
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    assert any(issue.field == "J_1" and "junction" in issue.reason for issue in result.issues)


def test_long_flowpath_names_are_cut_and_quoted_in_issue_reasons(tmp_path: Path) -> None:
    long_name = "FP_" + "A" * 60
    text = SMALL.replace("FP_IN", long_name).replace(
        f"{long_name},{long_name}_P2,SRC,J_1,", f"{long_name},{long_name}_P2,SRC,OUT_A,")
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    disagree = [issue for issue in result.issues if "disagree" in issue.reason]
    assert len(disagree) == 1
    assert f"'{long_name[:48]}'" in disagree[0].reason
    assert long_name not in disagree[0].reason


def test_long_node_names_are_cut_and_quoted_in_issue_reasons(tmp_path: Path) -> None:
    long_node = "OUT_" + "B" * 60
    text = SMALL.replace("OUT_B", long_node).replace(
        f",,,,,,,,,,,,{long_node},sink,", f",,,,,,,,,,,,{long_node},bogus,")
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    kinds = [issue for issue in result.issues if "node_kind" in issue.reason]
    assert len(kinds) == 1
    assert f"'{long_node[:48]}'" in kinds[0].reason
    assert long_node not in kinds[0].reason


def test_a_duplicate_boundary_row_names_both_rows(tmp_path: Path) -> None:
    lines = SMALL.splitlines()
    first = next(index + 1 for index, line in enumerate(lines) if line.startswith(",,,,,,,,,,,,OUT_B"))
    text = SMALL + ",,,,,,,,,,,,OUT_B,sink,1.0,25.0,0.5,0.0\n"
    second = len(lines) + 1
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    duplicates = [issue for issue in result.issues if "duplicate boundary" in issue.reason]
    assert len(duplicates) == 1
    assert duplicates[0].row == second
    assert str(first) in duplicates[0].reason


def test_every_exceeded_cap_is_listed_in_one_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    import olga_companion.pipe_table_import as module

    monkeypatch.setattr(module, "MAX_VALVES", 10)
    monkeypatch.setattr(module, "MAX_NODES", 100)
    result = _import("synthetic_network.csv")
    assert result.spec is None
    caps = [issue for issue in result.issues if issue.field == "caps"]
    assert len(caps) == 1 and "valves 66 > 10" in caps[0].reason and "nodes 134 > 100" in caps[0].reason


def test_missing_boundary_values_are_reported(tmp_path: Path) -> None:
    text = "\n".join(line for line in SMALL.splitlines() if not line.startswith(",,,,,,,,,,,,OUT_B")) + "\n"
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    assert any(issue.field == "OUT_B" for issue in result.issues)


def test_labels_are_deterministic() -> None:
    first, second = _import("small_branch.csv"), _import("small_branch.csv")
    assert first.label_map == second.label_map and first.spec == second.spec
    assert first.label_map["flowpaths"] == {"FP_IN": "FP_001", "FP_A": "FP_002", "FP_B": "FP_003"}


@pytest.mark.parametrize("value", ["0", "-3", "inf", "nan", "2e7"])
def test_impossible_pipe_lengths_are_row_issues(tmp_path: Path, value: str) -> None:
    text = SMALL.replace("FP_A,FP_A_P1,J_1,OUT_A,10.0,", f"FP_A,FP_A_P1,J_1,OUT_A,{value},", 1)
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    assert any(issue.field == "length_m" and issue.row == 7 for issue in result.issues)


def test_a_table_without_pipe_rows_is_refused(tmp_path: Path) -> None:
    text = "\n".join(line for line in SMALL.splitlines() if line.startswith(("flowpath", ",,"))) + "\n"
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None and "no pipe rows" in result.issues[0].reason


@pytest.mark.parametrize("max_section", [float("nan"), 0.0, -1.0, 1e-6])
def test_unusable_section_lengths_are_refused_before_segmenting(max_section: float) -> None:
    from dataclasses import replace

    result = _import("small_branch.csv", replace(OPTIONS, max_section_m=max_section))
    assert result.spec is None
    assert any(issue.field in {"max_section_m", "caps"} for issue in result.issues)


def test_a_closed_end_is_refused_with_its_row(tmp_path: Path) -> None:
    text = SMALL.replace(",,,,,,,,,,,,OUT_B,sink,2.0,25.0,0.5,0.0", ",,,,,,,,,,,,OUT_B,closed,,,,")
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    assert any(issue.field == "OUT_B" and issue.row == 4 and "closed" in issue.reason for issue in result.issues)


def test_a_valve_without_a_position_is_a_row_issue(tmp_path: Path) -> None:
    text = SMALL.replace("V_FP_A,0.5,", "V_FP_A,,", 1)
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert any(issue.field == "valve_position" for issue in result.issues)


@pytest.mark.parametrize("schedule", ["e:1", "--:1", "1.2.3:0"])
def test_unreadable_schedules_are_row_issues(tmp_path: Path, schedule: str) -> None:
    text = SMALL.replace('"0:1, 299:1, 300:0"', f'"{schedule}"', 1)
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert any(issue.field == "valve_schedule" for issue in result.issues)


def test_a_valve_without_an_opening_is_a_row_issue(tmp_path: Path) -> None:
    text = SMALL.replace(",0:1, 299:1, 300:0,", ",,", 1).replace('"0:1, 299:1, 300:0"', "")
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.spec is None
    assert any(issue.field == "valve_schedule" for issue in result.issues)


def test_no_valve_sits_on_the_first_boundary_after_a_junction() -> None:
    # OLGA 2022 aborts at time 0: "It is not possible to place a VALVE on the first
    # SECTIONBOUNDARY in a FlowPath next to the outlet of a JUNCTIONNODE".
    result = _import("synthetic_network.csv")
    spec = normalize_case_spec(result.spec)
    junctions = {node.label for node in spec.nodes if node.kind == "junction"}
    first_pipe = {fp.pipes[0].label for fp in spec.flowpaths if fp.from_node in junctions}
    sections = {p.label: p.sections for fp in spec.flowpaths for p in fp.pipes}
    checked = 0
    for valve in spec.equipment:
        if valve.pipe in first_pipe:
            checked += 1
            assert max(1, int(valve.position * sections[valve.pipe])) >= 2, valve.label
    assert checked > 0


@pytest.mark.parametrize("fixture", sorted(path.name for path in TABLES.glob("*.csv")))
def test_no_valve_sits_on_a_pipe_end(fixture: str) -> None:
    # M2: a valve after a junction sits inside its pipe, never on the pipe's
    # end. Every valve ships with position < 1.0; a valve on a valved first
    # pipe after a junction sits on 3+ sections, and the finer first pipes
    # keep the worst in-flowpath ratio in bounds. Applies to every fixture
    # with valves; a fixture without any contradicts this M2 coverage and
    # fails loudly instead of passing vacuously. A first pipe is the `_01`
    # pipe of its flowpath (labels count rows in flow order from 1), and a
    # junction start carries the `J_` prefix.
    result = _import(fixture)
    assert result.spec is not None, result.issues

    spec = normalize_case_spec(result.spec)
    flows = {flow.label: flow for flow in spec.flowpaths}
    sections = {pipe.label: pipe.sections for flow in spec.flowpaths for pipe in flow.pipes}
    assert spec.equipment, f"no valves in {fixture}"
    for valve in spec.equipment:
        assert valve.position < 1.0, (fixture, valve.label, valve.position)
        flow = flows[valve.flowpath]
        if valve.pipe.endswith("_01") and flow.from_node.startswith("J_"):
            assert sections[valve.pipe] >= 3, (fixture, valve.label, sections[valve.pipe])
    assert result.summary["worst_ratio_in_flowpaths"] <= OPTIONS.max_ratio


def test_a_pass_through_node_joins_its_two_flowpaths(tmp_path: Path) -> None:
    # OLGA 2022 blew up at a 1-in/1-out JUNCTIONNODE ("TEMPERATURE BELOW TABLE VALUES ...
    # T = -8.5e+09 C" in the section next to it, 0.001 s in), so the import joins the two
    # flowpaths into one instead of writing that junction.
    text = SMALL.replace("FP_IN,FP_IN_P2,SRC,J_1,", "FP_IN2,FP_IN2_P1,J_0,J_1,").replace(
        "FP_IN,FP_IN_P1,SRC,J_1,", "FP_IN,FP_IN_P1,SRC,J_0,"
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == ()
    spec = normalize_case_spec(result.spec)
    assert [node.label for node in spec.nodes if node.kind == "junction"] == ["J_001"]
    joined = next(fp for fp in spec.flowpaths if fp.from_node.startswith("SRC"))
    assert [pipe.length for pipe in joined.pipes] == [20.0, 5.0]
    assert result.label_map["flowpaths"]["FP_IN2"] == result.label_map["flowpaths"]["FP_IN"]
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean, compiled.validation.diagnostics


def test_a_joined_flowpath_keeps_each_source_pipe_name_in_the_label_map(tmp_path: Path) -> None:
    # Both flowpaths name their pipe SEG; the join must not let the second SEG overwrite the
    # first, and the second flowpath's SEG must stay reachable under its own flowpath name.
    text = SMALL.replace("FP_IN,FP_IN_P2,SRC,J_1,", "FP_IN2,SEG,J_0,J_1,").replace(
        "FP_IN,FP_IN_P1,SRC,J_1,", "FP_IN,SEG,SRC,J_0,"
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == ()
    assert result.label_map["pipes"]["FP_IN/SEG"] == "P_001_01"
    assert result.label_map["pipes"]["FP_IN2/SEG"] == "P_001_02"


def test_the_synthetic_network_has_no_pass_through_junction() -> None:
    spec = normalize_case_spec(_import("synthetic_network.csv").spec)
    degree: dict[str, list[int]] = {}
    for fp in spec.flowpaths:
        degree.setdefault(fp.from_node, [0, 0])[1] += 1
        degree.setdefault(fp.to_node, [0, 0])[0] += 1
    junctions = {node.label for node in spec.nodes if node.kind == "junction"}
    assert all(degree[label] != [1, 1] for label in junctions)


def test_a_table_case_lets_olga_take_small_time_steps() -> None:
    # MINDT=0.001 s and DTSTART=1 s left OLGA no room on 15 mm sections ("Criterion timestep
    # (0.00037 seconds) less than minimum timestep (0.001 seconds)") and a network of
    # split/merge bundles never ran. The owner's network deck that reaches NORMAL STOP in
    # OLGA 2022 uses MINDT=1E-08 s and DTSTART=1E-04 s.
    result = _import("small_branch.csv")
    integration = result.spec["integration"]
    assert integration["min_dt_s"] == 1e-08 and integration["dt_start_s"] == 1e-04
    text = case_compiler.compile_case_spec(result.spec).text
    line = next(row for row in text.splitlines() if row.startswith("INTEGRATION"))
    mindt = float(line.split("MINDT=")[1].split()[0])
    dtstart = float(line.split("DTSTART=")[1].split()[0])
    assert (mindt, dtstart) == (1e-08, 1e-04)


def test_a_table_case_starts_from_initial_conditions_not_the_steady_state_solver(tmp_path: Path) -> None:
    # With STEADYSTATE=ON a network of split/merge bundles filled case.out with "Internal
    # software error" and never finished; the same deck with STEADYSTATE=OFF and one
    # INITIALCONDITIONS line per flowpath reached NORMAL STOP in 2 s, as the owner's deck does.
    result = _import("small_branch.csv")
    spec = normalize_case_spec(result.spec)
    assert spec.integration.steady_state is False
    initial = spec.initial_conditions
    boundaries = [node for node in spec.nodes if node.kind in {"source", "sink"}]
    assert initial.pressure_pa == min(node.pressure_pa for node in boundaries)
    assert initial.temperature_c == 25.0 and initial.void_fraction == 1.0
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean, compiled.validation.diagnostics
    assert "OPTIONS STEADYSTATE=OFF" in compiled.text
    assert compiled.text.count("INITIALCONDITIONS PRESSURE=200000 Pa, TEMPERATURE=25 C, VOIDFRACTION=1") == len(spec.flowpaths)
    source = tmp_path / "case.genkey"
    source.write_bytes(compiled.compiled_bytes)
    assert recover_case_spec(source) == spec


def test_a_stated_start_state_is_used_and_the_automatic_one_is_flagged_on_a_large_drop(tmp_path: Path) -> None:
    # Started at the lowest boundary pressure, a 15 -> 6 bar network left the PVT table's
    # temperature range in the first millisecond (compression at the inlet); an 8 -> 6 bar
    # network reached NORMAL STOP. The user states the start state, or is told it was guessed.
    # The shipped template is now a small drop, so the large drop is built back for this pin.
    large = SMALL.replace("SRC,source,2.4", "SRC,source,5.0")
    automatic = build_case_spec(read_table(_write(tmp_path, large)), OPTIONS)
    assert automatic.summary["initial_state"] == {"pressure_pa": 200000.0, "temperature_c": 25.0, "stated": False}
    assert automatic.summary["start_warning"] == {"highest_pressure_pa": 500000.0, "lowest_pressure_pa": 200000.0}

    stated = _import("small_branch.csv", replace(OPTIONS, initial_pressure_pa=300000.0, initial_temperature_c=30.0))
    initial = stated.spec["initial_conditions"]
    assert (initial["pressure_pa"], initial["temperature_c"], initial["void_fraction"]) == (300000.0, 30.0, 1.0)
    assert stated.summary["initial_state"] == {"pressure_pa": 300000.0, "temperature_c": 30.0, "stated": True}
    assert stated.summary["start_warning"] is None


def test_a_small_pressure_drop_needs_no_start_warning(tmp_path: Path) -> None:
    # The sinks sit at 2 bar, so a small drop starts at 2.5 bar (ratio 1.25).
    text = SMALL.replace("SRC,source,2.4", "SRC,source,2.5")
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)
    assert result.summary["initial_state"]["stated"] is False
    assert result.summary["start_warning"] is None


@pytest.mark.parametrize("stated", [False, True])
def test_a_table_without_a_source_or_sink_is_refused_not_crashed(tmp_path: Path, stated: bool) -> None:
    # A loop with no boundary rows reached min() of an empty list (or a division by zero
    # when the start state was given) instead of naming what is missing.
    header = SMALL.splitlines()[0]
    text = "\n".join([
        header,
        "FP_1,P1,A,B,10.0,0.0,0.05,5e-05,,,,,,,,,,",
        "FP_2,P2,B,A,10.0,0.0,0.05,5e-05,,,,,,,,,,",
    ])
    options = replace(OPTIONS, initial_pressure_pa=2e5, initial_temperature_c=20.0) if stated else OPTIONS
    result = build_case_spec(read_table(_write(tmp_path, text)), options)
    assert result.spec is None
    assert any(issue.field == "topology" and "source" in issue.reason for issue in result.issues)


COORD_COLUMNS = [
    "flowpath", "pipe", "from_node", "to_node",
    "length_m", "elevation_m", "x_start_m", "y_start_m", "z_start_m",
    "x_m", "y_m", "z_m", "inner_diameter_m", "roughness_m",
    "node", "node_kind", "pressure_bar", "mass_flow_kg_s",
    "temperature_c", "gas_fraction", "water_fraction",
]


def _coord_rows(*rows: dict) -> str:
    lines = [",".join(COORD_COLUMNS)]
    for values in rows:
        lines.append(",".join("" if values.get(name) is None else str(values[name]) for name in COORD_COLUMNS))
    return "\n".join(lines) + "\n"


def _two_pipe_network(first: dict, second: dict) -> str:
    return _coord_rows(
        {"node": "SRC", "node_kind": "source", "pressure_bar": 5.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "SNK", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_1", "pipe": "P1", "from_node": "SRC", "to_node": "SNK",
         "inner_diameter_m": 0.05, "roughness_m": 5e-05, **first},
        {"flowpath": "FP_1", "pipe": "P2", "from_node": "SRC", "to_node": "SNK",
         "inner_diameter_m": 0.05, "roughness_m": 5e-05, **second},
    )


def _length_network() -> str:
    # P1 runs 10 m rising 6 m; P2 continues 5 m up from P1's end.
    return _two_pipe_network({"length_m": 10.0, "elevation_m": 6.0}, {"length_m": 5.0, "elevation_m": 0.0})


def _coord_network() -> str:
    # The same two pipes as end points: P1 ends at (8, 6, 0), P2 at (8, 6, 5).
    # The flowpath starts at the origin, so no start columns are needed.
    return _two_pipe_network({"x_m": 8.0, "y_m": 6.0, "z_m": 0.0}, {"x_m": 8.0, "y_m": 6.0, "z_m": 5.0})


def test_coordinate_rows_import_to_the_same_spec_as_length_rows(tmp_path: Path) -> None:
    from_coords = build_case_spec(read_table(_write(tmp_path, _coord_network())), OPTIONS)
    from_lengths = build_case_spec(read_table(_write(tmp_path, _length_network())), OPTIONS)

    assert from_coords.issues == (), from_coords.issues
    assert from_lengths.issues == ()
    assert from_coords.spec == from_lengths.spec


def test_a_flowpath_start_defaults_to_the_origin_unless_stated(tmp_path: Path) -> None:
    # P1 starts at (1, 0, 0) and ends at (9, 6, 0): still 10 m rising 6 m.
    # P2 chains from P1's end to (9, 6, 5): still 5 m flat.
    text = _two_pipe_network(
        {"x_start_m": 1.0, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 9.0, "y_m": 6.0, "z_m": 0.0},
        {"x_m": 9.0, "y_m": 6.0, "z_m": 5.0},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == (), result.issues
    assert result.spec == build_case_spec(read_table(_write(tmp_path, _length_network())), OPTIONS).spec


def test_mixed_coordinate_and_length_rows_are_refused_naming_the_row(tmp_path: Path) -> None:
    text = _two_pipe_network(
        {"length_m": 10.0, "elevation_m": 0.0}, {"x_m": 8.0, "y_m": 0.0, "z_m": 5.0})
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any("mix" in issue.reason and issue.row == 5 for issue in result.issues)


def test_a_zero_length_coordinate_pipe_is_refused(tmp_path: Path) -> None:
    text = _two_pipe_network(
        {"x_m": 8.0, "y_m": 6.0, "z_m": 0.0}, {"x_m": 8.0, "y_m": 6.0, "z_m": 0.0})
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any("zero length" in issue.reason and issue.row == 5 for issue in result.issues)


def _branched_coord_network() -> str:
    # FP_IN runs from the origin to J_1 at (100, 0, 0); both branches chain
    # from that shared node position.
    return _coord_rows(
        {"node": "SRC", "node_kind": "source", "pressure_bar": 5.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "OUT_A", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"node": "OUT_B", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_IN", "pipe": "P1", "from_node": "SRC", "to_node": "J_1",
         "x_m": 100.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_A", "pipe": "P1", "from_node": "J_1", "to_node": "OUT_A",
         "x_m": 150.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_B", "pipe": "P1", "from_node": "J_1", "to_node": "OUT_B",
         "x_m": 100.0, "y_m": -30.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )


def test_branches_chain_from_the_shared_node_position(tmp_path: Path) -> None:
    result = build_case_spec(read_table(_write(tmp_path, _branched_coord_network())), OPTIONS)

    assert result.issues == (), result.issues
    lengths = {
        pipe["label"]: pipe["length_m"]
        for flowpath in result.spec["flowpaths"] for pipe in flowpath["pipes"]
    }
    assert lengths == {"P_001_01": 100.0, "P_002_01": 50.0, "P_003_01": 30.0}


def _canon(result) -> dict:
    """Label-free view of an import: labels follow row order, so two row orders
    of one network can only be equal once labels are mapped back to names."""
    label_map = result.label_map
    inv_nodes = {label: name for name, label in label_map["nodes"].items()}
    inv_flowpaths = {label: name for name, label in label_map["flowpaths"].items()}
    inv_pipes = {label: key.split("/", 1)[1] for key, label in label_map["pipes"].items()}
    spec = result.spec
    return {
        "nodes": {
            inv_nodes[node["label"]]: {k: v for k, v in node.items() if k != "label"}
            for node in spec["nodes"]
        },
        "flowpaths": {
            inv_flowpaths[flowpath["label"]]: {
                "from": inv_nodes[flowpath["from"]],
                "to": inv_nodes[flowpath["to"]],
                "pipes": [
                    {k: v for k, v in pipe.items() if k != "label"}
                    for pipe in flowpath["pipes"]
                ],
            }
            for flowpath in spec["flowpaths"]
        },
        "sources": [
            {
                **{k: v for k, v in source.items() if k not in ("label", "flowpath", "pipe")},
                "flowpath": inv_flowpaths[source["flowpath"]],
                "pipe": inv_pipes[source["pipe"]],
            }
            for source in spec.get("massflow_sources", [])
        ],
        "rest": {
            k: v for k, v in spec.items()
            if k not in ("nodes", "flowpaths", "massflow_sources")
        },
    }


def test_branch_rows_before_the_trunk_import_to_the_same_spec(tmp_path: Path) -> None:
    trunk_first = _branched_coord_network()
    rows = trunk_first.splitlines()
    # Branches FP_A/FP_B before the FP_IN trunk; node rows keep their lines.
    reordered = "\n".join([rows[0], rows[1], rows[2], rows[3], rows[5], rows[6], rows[4]]) + "\n"
    first = build_case_spec(read_table(_write(tmp_path, trunk_first)), OPTIONS)
    second = build_case_spec(read_table(_write(tmp_path, reordered)), OPTIONS)

    assert first.issues == () and second.issues == (), (first.issues, second.issues)
    assert _canon(first) == _canon(second)
    assert _canon(first)["flowpaths"]["FP_A"]["pipes"][0]["length_m"] == 50.0


def _merge_coord_network() -> str:
    # Two branches merge at J_1 and run on; both inlets state their start, so
    # no origin is assumed anywhere.
    return _coord_rows(
        {"node": "SRC_A", "node_kind": "source", "pressure_bar": 5.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "SRC_B", "node_kind": "source", "pressure_bar": 4.0,
         "temperature_c": 30.0, "gas_fraction": 0.9, "water_fraction": 0.0},
        {"node": "SNK", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_A", "pipe": "P1", "from_node": "SRC_A", "to_node": "J_1",
         "x_start_m": 0.0, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 100.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_B", "pipe": "P1", "from_node": "SRC_B", "to_node": "J_1",
         "x_start_m": 0.0, "y_start_m": 40.0, "z_start_m": 0.0,
         "x_m": 100.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_C", "pipe": "P1", "from_node": "J_1", "to_node": "SNK",
         "x_m": 110.0, "y_m": 10.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )


def test_a_merge_imports_to_the_same_spec_in_any_row_order(tmp_path: Path) -> None:
    branches_first = _merge_coord_network()
    rows = branches_first.splitlines()
    onward_first = "\n".join([rows[0], rows[1], rows[2], rows[3], rows[6], rows[4], rows[5]]) + "\n"
    first = build_case_spec(read_table(_write(tmp_path, branches_first)), OPTIONS)
    second = build_case_spec(read_table(_write(tmp_path, onward_first)), OPTIONS)

    assert first.issues == () and second.issues == (), (first.issues, second.issues)
    assert _canon(first) == _canon(second)
    assert first.summary["coordinate_origin_assumed"] is False
    pipes = {
        name: flowpath["pipes"][0]
        for name, flowpath in _canon(first)["flowpaths"].items()
    }
    assert pipes["FP_A"]["length_m"] == 100.0
    assert pipes["FP_C"]["length_m"] == math.dist((100.0, 0.0, 0.0), (110.0, 10.0, 0.0))
    assert pipes["FP_C"]["elevation_m"] == 10.0


def test_a_branch_that_moves_its_shared_node_is_refused(tmp_path: Path) -> None:
    text = _coord_rows(
        {"node": "SRC", "node_kind": "source", "pressure_bar": 5.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "OUT_A", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_IN", "pipe": "P1", "from_node": "SRC", "to_node": "J_1",
         "x_m": 100.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_A", "pipe": "P1", "from_node": "J_1", "to_node": "OUT_A",
         "x_start_m": 100.05, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 150.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any("mm" in issue.reason and issue.row == 5 for issue in result.issues)


def test_a_second_start_less_inlet_is_refused_once_a_start_is_stated(tmp_path: Path) -> None:
    text = _coord_rows(
        {"node": "SRC", "node_kind": "source", "pressure_bar": 5.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "SRC2", "node_kind": "source", "pressure_bar": 4.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "SNK", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_1", "pipe": "P1", "from_node": "SRC", "to_node": "J_1",
         "x_start_m": 0.0, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 100.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_2", "pipe": "P1", "from_node": "SRC2", "to_node": "J_1",
         "x_m": 0.0, "y_m": 40.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_3", "pipe": "P1", "from_node": "J_1", "to_node": "SNK",
         "x_m": 110.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any("x_start_m" in issue.reason and issue.row == 6 for issue in result.issues)


def test_an_assumed_origin_is_flagged_in_the_summary(tmp_path: Path) -> None:
    result = build_case_spec(read_table(_write(tmp_path, _coord_network())), OPTIONS)

    assert result.issues == (), result.issues
    assert result.summary["coordinate_origin_assumed"] is True


def test_a_stated_start_leaves_no_origin_flag(tmp_path: Path) -> None:
    text = _two_pipe_network(
        {"x_start_m": 1.0, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 9.0, "y_m": 6.0, "z_m": 0.0},
        {"x_m": 9.0, "y_m": 6.0, "z_m": 5.0},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == (), result.issues
    assert result.summary["coordinate_origin_assumed"] is False


def test_a_second_inlet_without_a_start_is_refused(tmp_path: Path) -> None:
    text = _coord_rows(
        {"node": "SRC", "node_kind": "source", "pressure_bar": 5.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "SRC2", "node_kind": "source", "pressure_bar": 4.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "SNK", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_1", "pipe": "P1", "from_node": "SRC", "to_node": "J_1",
         "x_m": 100.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_2", "pipe": "P1", "from_node": "SRC2", "to_node": "J_1",
         "x_m": 0.0, "y_m": 40.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_3", "pipe": "P1", "from_node": "J_1", "to_node": "SNK",
         "x_m": 110.0, "y_m": 0.0, "z_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any("x_start_m" in issue.reason and issue.row == 6 for issue in result.issues)


def test_partial_start_columns_are_refused_naming_the_row(tmp_path: Path) -> None:
    text = _two_pipe_network(
        {"x_start_m": 1.0, "x_m": 9.0, "y_m": 6.0, "z_m": 0.0},
        {"x_m": 9.0, "y_m": 6.0, "z_m": 5.0},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any(issue.field == "x_start_m" and issue.row == 4 for issue in result.issues)


def test_a_later_start_must_match_the_previous_end(tmp_path: Path) -> None:
    text = _two_pipe_network(
        {"x_m": 8.0, "y_m": 6.0, "z_m": 0.0},
        {"x_start_m": 0.0, "y_start_m": 0.0, "z_start_m": 0.0,
         "x_m": 8.0, "y_m": 6.0, "z_m": 5.0},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any(issue.field == "x_start_m" and issue.row == 5 for issue in result.issues)


def test_informational_position_columns_do_not_block_a_length_table(tmp_path: Path) -> None:
    text = "\n".join([
        "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
        "X,Y,Z,node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction",
        ",,,,,,,,0,0,0,SRC,source,5.0,25.0,1.0,0.0",
        ",,,,,,,,0,0,0,SNK,sink,1.0,25.0,0.5,0.0",
        "FP_1,P1,SRC,SNK,10.0,6.0,0.05,5e-05,1,2,3,,,,,,",
        "FP_1,P2,SRC,SNK,5.0,0.0,0.05,5e-05,4,5,6,,,,,,",
    ]) + "\n"
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == (), result.issues
    assert [pipe["length_m"] for pipe in result.spec["flowpaths"][0]["pipes"]] == [10.0, 5.0]


def test_a_mass_flow_unit_other_than_kg_s_is_refused(tmp_path: Path) -> None:
    text = "\n".join([
        "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
        "node,node_kind,Mass Flow (lb),temperature_c,gas_fraction,water_fraction",
        ",,,,,,,,,WELL,closed,5.5,40.0,1.0,0.0",
        ",,,,,,,,,SNK,sink,1.0,25.0,0.5,0.0",
        "FP_1,P1,WELL,SNK,10.0,2.0,0.05,5e-05,,,,,,",
    ]) + "\n"
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any("kg/s" in issue.reason and issue.row == 2 for issue in result.issues)


def test_a_redundant_matching_start_is_accepted(tmp_path: Path) -> None:
    text = _two_pipe_network(
        {"x_m": 8.0, "y_m": 6.0, "z_m": 0.0},
        {"x_start_m": 8.0, "y_start_m": 6.0, "z_start_m": 0.0,
         "x_m": 8.0, "y_m": 6.0, "z_m": 5.0},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == (), result.issues
    assert result.spec == build_case_spec(
        read_table(_write(tmp_path, _length_network())), OPTIONS).spec


def _closed_inlet_network(extra: dict) -> str:
    closed = {"node": "WELL", "node_kind": "closed", "temperature_c": 40.0,
              "gas_fraction": 1.0, "water_fraction": 0.0}
    closed.update(extra)
    return _coord_rows(
        closed,
        {"node": "SNK", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_1", "pipe": "P1", "from_node": "WELL", "to_node": "SNK",
         "length_m": 10.0, "elevation_m": 2.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )


def test_a_closed_inlet_becomes_a_closed_node_with_a_massflow_source(tmp_path: Path) -> None:
    result = build_case_spec(
        read_table(_write(tmp_path, _closed_inlet_network({"mass_flow_kg_s": 2.5}))), OPTIONS)

    assert result.issues == (), result.issues
    spec = normalize_case_spec(result.spec)
    assert [node.label for node in spec.nodes if node.kind == "closed"] == ["CLS_001"]
    (source,) = spec.massflow_sources
    assert (source.flowpath, source.pipe, source.section) == (
        spec.flowpaths[0].label, spec.flowpaths[0].pipes[0].label, 1)
    assert (source.mass_flow_kg_s, source.temperature_c, source.gas_fraction) == (2.5, 40.0, 1.0)
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean, compiled.validation.diagnostics
    assert "TYPE=CLOSED" in compiled.text
    assert 'SOURCE LABEL="MS_001"' in compiled.text


@pytest.mark.parametrize("extra", [{}, {"mass_flow_kg_s": 0.0}])
def test_a_closed_inlet_without_a_positive_mass_flow_is_refused(tmp_path: Path, extra: dict) -> None:
    result = build_case_spec(read_table(_write(tmp_path, _closed_inlet_network(extra))), OPTIONS)

    assert result.spec is None
    assert any(issue.field == "WELL" and issue.row == 2 for issue in result.issues)


@pytest.mark.parametrize("extra", [
    {"mass_flow_kg_s": 2e6},
    {"mass_flow_kg_s": 2.5, "temperature_c": float("nan")},
    {"mass_flow_kg_s": 2.5, "gas_fraction": 3.0},
    {"mass_flow_kg_s": 2.5, "water_fraction": -0.5},
])
def test_a_closed_inlet_with_an_out_of_range_value_is_refused(tmp_path: Path, extra: dict) -> None:
    result = build_case_spec(read_table(_write(tmp_path, _closed_inlet_network(extra))), OPTIONS)

    assert result.spec is None
    assert any(issue.field == "WELL" and issue.row == 2 for issue in result.issues)


def test_a_source_with_an_out_of_range_fraction_is_refused(tmp_path: Path) -> None:
    text = SMALL.replace("SRC,source,2.4,25.0,1.0,0.0", "SRC,source,2.4,25.0,3.0,0.0")
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any(issue.field == "SRC" for issue in result.issues)


def test_a_closed_node_at_an_outlet_stays_an_issue(tmp_path: Path) -> None:
    text = _coord_rows(
        {"node": "SRC", "node_kind": "source", "pressure_bar": 5.0,
         "temperature_c": 25.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "WELL", "node_kind": "closed", "mass_flow_kg_s": 2.5,
         "temperature_c": 40.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"flowpath": "FP_1", "pipe": "P1", "from_node": "SRC", "to_node": "WELL",
         "length_m": 10.0, "elevation_m": 2.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert any(issue.field == "WELL" for issue in result.issues)


def test_a_closed_inlet_sets_the_start_state_without_a_pressure_source(tmp_path: Path) -> None:
    result = build_case_spec(
        read_table(_write(tmp_path, _closed_inlet_network({"mass_flow_kg_s": 2.5}))), OPTIONS)

    assert result.issues == (), result.issues
    initial = result.spec["initial_conditions"]
    assert (initial["pressure_pa"], initial["temperature_c"], initial["void_fraction"]) == (
        100000.0, 40.0, 1.0)


def test_the_start_state_averages_a_source_and_a_closed_inlet(tmp_path: Path) -> None:
    text = _coord_rows(
        {"node": "SRC", "node_kind": "source", "pressure_bar": 2.0,
         "temperature_c": 25.0, "gas_fraction": 0.8, "water_fraction": 0.0},
        {"node": "WELL", "node_kind": "closed", "mass_flow_kg_s": 2.5,
         "temperature_c": 40.0, "gas_fraction": 1.0, "water_fraction": 0.0},
        {"node": "SNK", "node_kind": "sink", "pressure_bar": 1.0,
         "temperature_c": 25.0, "gas_fraction": 0.5, "water_fraction": 0.0},
        {"flowpath": "FP_A", "pipe": "P1", "from_node": "SRC", "to_node": "J_1",
         "length_m": 10.0, "elevation_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_B", "pipe": "P1", "from_node": "WELL", "to_node": "J_1",
         "length_m": 8.0, "elevation_m": 0.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
        {"flowpath": "FP_C", "pipe": "P1", "from_node": "J_1", "to_node": "SNK",
         "length_m": 6.0, "elevation_m": 1.0, "inner_diameter_m": 0.05, "roughness_m": 5e-05},
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == (), result.issues
    initial = result.spec["initial_conditions"]
    assert (initial["pressure_pa"], initial["temperature_c"], initial["void_fraction"]) == (
        100000.0, 32.5, 0.9)
    assert len(result.spec["massflow_sources"]) == 1


@pytest.mark.parametrize(("old", "new", "field"), [
    ("FP_IN,FP_IN_P1,SRC,J_1,20.0,0.0,", "FP_IN,FP_IN_P1,SRC,J_1,20.0,5000.0,", "elevation_m"),
    ("FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,", "FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,40.0,", "inner_diameter_m"),
    ("FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,5e-05,", "FP_B,FP_B_P1,J_1,OUT_B,8.0,-1.0,0.04,0.5,", "roughness_m"),
])
def test_a_value_in_the_wrong_unit_is_named_by_its_row_and_column(tmp_path: Path, old: str, new: str, field: str) -> None:
    # Millimetres read as metres failed only in the CaseSpec check, with no row and a
    # generic sentence that never named the column.
    assert old in SMALL
    result = build_case_spec(read_table(_write(tmp_path, SMALL.replace(old, new))), OPTIONS)
    assert result.spec is None
    assert [(issue.row is not None, issue.field) for issue in result.issues] == [(True, field)]


# Pins: default import output measured by importing each fixture in this
# worktree and hashing the canonical JSON spec (sha256 of sort_keys JSON),
# plus the measured section count, worst in-flowpath ratio and
# junction-warning count. The synthetic entry was re-measured after M2 gave
# every valved first pipe after a junction at least 3 sections (1478 -> 1499
# sections, worst 1.827 -> 1.828, warnings 64 -> 65). The small_branch entry
# was re-measured after its sinks moved to 2 bar (digest changed, sections
# 55, worst 1.6 and 0 warnings held) and again after its source moved to
# 2.4 bar (digest changed, sections 55, worst 1.6 and 0 warnings held). Both
# were re-measured after valves got a section edge at their exact table position
# (small_branch 55 -> 47 sections, worst 1.6 -> 1.739; synthetic 1499 -> 1512
# sections, worst 1.828 -> 2.0, warnings 65 held).
_HEAD_PINS = {
    "small_branch.csv": (
        "7bc357f65df063705ea4fbacc1438279b0d861e1791cd3ef6f050fcf30771d24", 47, 1.739, 0),
    "synthetic_network.csv": (
        "ea391f610b9adba466c765a9971bc48bbc5c00da8de6bce57ed299331dcbfa48", 1512, 2.0, 65),
}


@pytest.mark.parametrize("fixture", ["small_branch.csv", "synthetic_network.csv"])
def test_default_output_matches_the_pinned_output(fixture: str) -> None:
    import hashlib
    import json

    result = _import(fixture)
    digest, sections, worst, warnings = _HEAD_PINS[fixture]

    assert result.issues == ()
    assert hashlib.sha256(json.dumps(result.spec, sort_keys=True).encode()).hexdigest() == digest
    assert result.summary["sections"] == sections
    assert result.summary["worst_ratio_in_flowpaths"] == worst
    assert len(result.summary["junction_ratio_warnings"]) == warnings


def test_a_looser_max_ratio_warns_less_on_the_same_mesh() -> None:
    from dataclasses import replace as _replace

    default = _import("synthetic_network.csv")
    loose = _import("synthetic_network.csv", _replace(OPTIONS, max_ratio=4.0))

    assert loose.issues == ()
    assert loose.summary["sections"] == default.summary["sections"]
    assert len(loose.summary["junction_ratio_warnings"]) < len(default.summary["junction_ratio_warnings"])


def test_a_tighter_max_ratio_grades_closer_and_warns_more() -> None:
    from dataclasses import replace as _replace

    default = _import("synthetic_network.csv")
    tight = _import("synthetic_network.csv", _replace(OPTIONS, max_ratio=1.2))

    assert tight.issues == ()
    assert tight.summary["worst_ratio_in_flowpaths"] < default.summary["worst_ratio_in_flowpaths"]
    assert len(tight.summary["junction_ratio_warnings"]) > len(default.summary["junction_ratio_warnings"])


def test_max_ratio_binds_within_pipe_growth() -> None:
    from dataclasses import replace as _replace

    loose = _import("small_branch.csv", _replace(OPTIONS, max_ratio=2.0))
    tight = _import("small_branch.csv", _replace(OPTIONS, max_ratio=1.2))

    assert tight.issues == () and loose.issues == ()
    assert tight.spec != loose.spec


@pytest.mark.parametrize("ratio", [float("nan"), 0.0, -1.0, 0.5])
def test_an_unusable_max_ratio_is_refused_before_segmenting(ratio: float) -> None:
    from dataclasses import replace as _replace

    result = _import("small_branch.csv", _replace(OPTIONS, max_ratio=ratio))
    assert result.spec is None
    assert any(issue.field == "max_ratio" for issue in result.issues)


def _with_start_voids(values: dict[str, str]) -> str:
    """SMALL with an initial_void_fraction column; values maps flowpath -> cell text."""
    lines = SMALL.strip().splitlines()
    out = [lines[0] + ",initial_void_fraction"]
    for line in lines[1:]:
        out.append(line + "," + values.get(line.split(",", 1)[0], ""))
    return "\n".join(out) + "\n"


def test_a_start_void_column_sets_each_flowpath_start_and_recovers(tmp_path: Path) -> None:
    text = _with_start_voids({"FP_IN": "0", "FP_A": "0.25"})
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == ()
    labels = result.label_map["flowpaths"]
    by_label = {fp["label"]: fp for fp in result.spec["flowpaths"]}
    assert by_label[labels["FP_IN"]]["initial_void_fraction"] == 0.0
    assert by_label[labels["FP_A"]]["initial_void_fraction"] == 0.25
    assert "initial_void_fraction" not in by_label[labels["FP_B"]]
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean, compiled.validation.diagnostics
    starts = [line for line in compiled.text.splitlines() if "INITIALCONDITIONS" in line]
    assert [line.rsplit("VOIDFRACTION=", 1)[1] for line in starts] == ["0", "0.25", "1"]
    source = tmp_path / "case.genkey"
    source.write_bytes(compiled.compiled_bytes)
    # Which void the file shares is not written in it; recovery must re-render the same bytes.
    recovered = recover_case_spec(source)
    assert case_compiler.compile_case_spec(recovered).compiled_bytes == compiled.compiled_bytes


def test_a_start_void_outside_zero_to_one_is_a_row_issue(tmp_path: Path) -> None:
    text = _with_start_voids({"FP_A": "1.5"})
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert [issue.code for issue in result.issues] == ["initial_void_fraction_out_of_range"]
    assert result.issues[0].row == 7


def test_joined_flowpaths_with_different_start_voids_are_refused(tmp_path: Path) -> None:
    text = (
        "flowpath,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
        "initial_void_fraction,node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction\n"
        ",,,,,,,,SRC,source,2.4,25,1,0\n"
        ",,,,,,,,OUT,sink,2.0,25,1,0\n"
        "UP,SRC,J_1,10,0,0.05,5e-05,0,,,,,,\n"
        "DOWN,J_1,OUT,10,0,0.05,5e-05,1,,,,,,\n"
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.spec is None
    assert [issue.code for issue in result.issues] == ["initial_void_fraction_disagrees"]
    assert result.issues[0].params == {"flowpath": "UP", "joined": "DOWN"}


def _valve_distances(result) -> dict[str, float]:
    """Distance of each valve from its flowpath start, from the compiled section lengths."""
    spec = normalize_case_spec(result.spec)
    found = {}
    for flow in spec.flowpaths:
        start = 0.0
        for pipe in flow.pipes:
            lengths = pipe.segment_lengths_m or (pipe.length / pipe.sections,) * pipe.sections
            for valve in spec.equipment:
                if valve.pipe == pipe.label:
                    boundary = min(max(1, int(valve.position * pipe.sections)), pipe.sections)
                    found[valve.label] = start + math.fsum(lengths[:boundary])
            start += pipe.length
    return found


def test_a_valve_lands_where_the_table_says(tmp_path: Path) -> None:
    text = SMALL.replace("V_FP_A,0.5,", "V_FP_A,0.37,")
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == ()
    assert abs(_valve_distances(result)["V_001"] - 3.7) <= 1e-3
    assert case_compiler.compile_case_spec(result.spec).validation.clean


def test_a_valve_at_a_pipe_outlet_sits_on_that_pipes_last_boundary(tmp_path: Path) -> None:
    # Pipe P1 of FP_A carries the valve at 1.0 and P2 follows it in the same flowpath.
    text = SMALL.replace(
        "FP_A,FP_A_P1,J_1,OUT_A,10.0,0.0,0.04,5e-05,V_FP_A,0.5,",
        "FP_A,FP_A_P1,J_1,OUT_A,10.0,0.0,0.04,5e-05,V_FP_A,1.0,",
    ).replace(
        "FP_B,FP_B_P1,", "FP_A,FP_A_P2,J_1,OUT_A,6.0,0.0,0.04,5e-05,,,,,,,,,,\nFP_B,FP_B_P1,", 1,
    )
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == (), result.issues
    assert abs(_valve_distances(result)["V_001"] - 10.0) <= 1e-3
    assert case_compiler.compile_case_spec(result.spec).validation.clean


def test_a_valve_at_the_outlet_of_a_flowpath_into_a_junction_lands_on_its_end(tmp_path: Path) -> None:
    # FP_IN ends at junction J_1: a valve at 1.0 on its last pipe sits on that pipe's outlet.
    text = SMALL.replace(
        "FP_IN,FP_IN_P2,SRC,J_1,5.0,2.0,0.05,5e-05,,,,,",
        'FP_IN,FP_IN_P2,SRC,J_1,5.0,2.0,0.05,5e-05,V_OUT,1.0,0.05,1,', 1)
    assert text != SMALL
    result = build_case_spec(read_table(_write(tmp_path, text)), OPTIONS)

    assert result.issues == ()
    valve = next(v for v in result.spec["equipment"] if v["label"] == result.label_map["valves"]["V_OUT"])
    assert valve["position"] == 1.0
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean, compiled.validation.diagnostics
