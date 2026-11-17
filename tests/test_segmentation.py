"""Graded segmentation and the neighbouring-section ratio check (P008)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from olga_companion import genkey_static
from olga_companion.segmentation import PipeRun, junction_ratio_warnings, segment_flowpath

FIXTURES = Path(__file__).parent / "fixtures" / "cases"


def _sequence(result) -> list[float]:
    return [cell for pipe in result.lengths_m for cell in pipe]


def _worst(cells: list[float]) -> float:
    return max(max(a, b) / min(a, b) for a, b in zip(cells, cells[1:]))


def test_short_pipe_next_to_long_pipe_grades_without_a_ratio_jump() -> None:
    result = segment_flowpath([PipeRun(0.045), PipeRun(4.0)], max_section_m=1.0)

    cells = _sequence(result)
    assert _worst(cells) <= 2.0
    assert result.worst_ratio <= 2.0 and result.warnings == ()
    # Grading, not a uniform 45 mm split of the long pipe: far fewer than 4.0/0.0225 sections.
    assert len(result.lengths_m[1]) <= 2 * math.log2(4.0 / 0.0225) + math.ceil(4.0 / 1.0) + 2


@pytest.mark.parametrize("lengths", [[10.0], [0.5, 30.0, 0.2, 7.0], [120.0, 3.0, 3.0, 450.0]])
def test_every_rule_holds(lengths: list[float]) -> None:
    result = segment_flowpath([PipeRun(length) for length in lengths], max_section_m=5.0)

    for length, cells in zip(lengths, result.lengths_m):
        assert len(cells) >= 2
        assert max(cells) <= 5.0 + 1e-9
        assert math.isclose(math.fsum(cells), length, rel_tol=1e-9)
    assert _worst(_sequence(result)) <= 2.0


def test_a_valved_pipe_before_two_short_pipes_stays_within_the_ratio() -> None:
    # Fitting the valved pipe to its length stretched its last section past 2x the next
    # pipe's first section before the coupling seeds kept shrinking.
    pipes = [PipeRun(1.2, valve_positions=(0.5,)), PipeRun(0.4), PipeRun(0.25)]
    for start in (False, True):
        for end in (False, True):
            result = segment_flowpath(pipes, max_section_m=1.0, refine_start=start, refine_end=end)
            assert _worst(_sequence(result)) <= 2.0, (start, end, result.lengths_m)


def test_a_valve_gets_a_nearby_boundary_and_finer_sections() -> None:
    plain = segment_flowpath([PipeRun(20.0)], max_section_m=2.0)
    valved = segment_flowpath([PipeRun(20.0, valve_positions=(0.5,))], max_section_m=2.0)

    (boundary,) = valved.valve_boundaries[0]
    edge = math.fsum(valved.lengths_m[0][:boundary])
    assert abs(edge - 10.0) <= max(valved.lengths_m[0]) / 2
    assert min(valved.lengths_m[0]) < min(plain.lengths_m[0])
    assert _worst(list(valved.lengths_m[0])) <= 2.0


def test_refined_ends_start_small() -> None:
    result = segment_flowpath([PipeRun(20.0)], max_section_m=2.0, refine_start=True, refine_end=True)

    cells = result.lengths_m[0]
    assert cells[0] < max(cells) and cells[-1] < max(cells)


def test_segmentation_is_deterministic() -> None:
    pipes = [PipeRun(0.3), PipeRun(12.0, valve_positions=(0.25, 0.8)), PipeRun(2.0)]
    assert segment_flowpath(pipes, max_section_m=1.0) == segment_flowpath(pipes, max_section_m=1.0)


def test_junction_ratio_warnings() -> None:
    rows = [("J_1", "FP_A", 1.0), ("J_1", "FP_B", 1.5), ("J_2", "FP_C", 0.2), ("J_2", "FP_D", 1.0)]
    assert junction_ratio_warnings(rows) == ["sections meeting at J_2 differ by 5.00x"]


def _validator_report(tmp_path: Path, text: str) -> tuple[int, str]:
    path = tmp_path / "case.genkey"
    path.write_text(text, encoding="utf-8")
    result = genkey_static.run_tool("validator", [str(path)])
    return result.exit_code, result.stdout


def _deck(lsegments: list[str]) -> str:
    pipes = "\n".join(
        f" PIPE LABEL=P{index}, ROUGHNESS=0.00005 m, NSEGMENT={len(segs.split(','))}, "
        f"LSEGMENT=({segs}) m, LENGTH={sum(float(v) for v in segs.split(','))} m, ELEVATION=0 m, DIAMETER=0.1 m"
        for index, segs in enumerate(lsegments, start=1)
    )
    return (
        'OPTIONS STEADYSTATE=ON, COMPOSITIONAL=OFF, FLOWMODEL=OLGAHD, TEMPERATURE=ADIABATIC\n'
        'FILES PVTFILE="fluid.tab"\n'
        'INTEGRATION ENDTIME=60 s, MINDT=0.001 s, STARTTIME=0 s, DTSTART=1 s\n'
        'NETWORKCOMPONENT TYPE=FLOWPATH, TAG=FP\n PARAMETERS LABEL="FP"\n BRANCH FLUID="F"\n'
        f' GEOMETRY LABEL="G"\n{pipes}\nENDNETWORKCOMPONENT\n'
        'NETWORKCOMPONENT TYPE=NODE, TAG=IN\n PARAMETERS LABEL="IN", TYPE=PRESSURE, PRESSURE=2 bara, TEMPERATURE=20 C\nENDNETWORKCOMPONENT\n'
        'NETWORKCOMPONENT TYPE=NODE, TAG=OUT\n PARAMETERS LABEL="OUT", TYPE=PRESSURE, PRESSURE=1 bara, TEMPERATURE=20 C\nENDNETWORKCOMPONENT\n'
        'CONNECTION TERMINALS = (IN FLOWTERM_1, FP INLET)\nCONNECTION TERMINALS = (OUT FLOWTERM_1, FP OUTLET)\nENDCASE\n'
    )


def test_validator_flags_a_section_jump_across_pipes(tmp_path: Path) -> None:
    exit_code, report = _validator_report(tmp_path, _deck(["1,1", "3,3"]))
    # A warning, not an error: existing decks must not start failing validation.
    assert exit_code == 0
    assert report.count("P008") == 1 and "WARNINGS: 1" in report


def test_validator_is_quiet_on_graded_sections(tmp_path: Path) -> None:
    exit_code, report = _validator_report(tmp_path, _deck(["1,1", "2,2,2"]))
    assert exit_code == 0 and "P008" not in report


@pytest.mark.parametrize("name", ["simple_pipeline.genkey", "second_pipeline.genkey"])
def test_existing_cases_keep_their_validator_status(name: str) -> None:
    result = genkey_static.run_tool("validator", [str(FIXTURES / name)])
    assert result.exit_code == 0


@pytest.mark.parametrize("start,end", [(False, True), (True, True), (True, False)])
def test_no_section_is_shorter_than_half_the_shortest_pipe(start: bool, end: bool) -> None:
    # Refining a 30 mm pipe at a junction used to cut 7 mm sections; OLGA's time step follows
    # the shortest section, so a 20 s run of the synthetic network never reached its first output.
    pipes = [PipeRun(0.3, valve_positions=(0.5,)), PipeRun(0.03), PipeRun(4.0)]
    result = segment_flowpath(pipes, max_section_m=1.0, refine_start=start, refine_end=end)

    assert min(_sequence(result)) >= 0.015 - 1e-12
    for length, cells in zip((0.3, 0.03, 4.0), result.lengths_m):
        assert math.isclose(math.fsum(cells), length, rel_tol=1e-9)


def test_a_ratio_the_floor_cannot_meet_is_reported() -> None:
    # A 30 mm pipe after a refined valve: the floor wins and the jump is named, not hidden.
    result = segment_flowpath([PipeRun(0.03), PipeRun(0.03)], max_section_m=1.0, refine_end=True)

    assert min(_sequence(result)) >= 0.015 - 1e-12
    assert (result.worst_ratio > 2.0) == bool(result.warnings)


def test_a_short_first_pipe_falls_back_to_an_even_split() -> None:
    # A 50 mm first pipe with first_min_sections=3 targets below the flowpath
    # floor, so the graded march cannot hold three sections and the pipe is
    # split evenly instead.
    result = segment_flowpath([PipeRun(0.05)], max_section_m=1.0, first_min_sections=3)

    assert len(result.lengths_m[0]) == 3
    assert math.isclose(math.fsum(result.lengths_m[0]), 0.05, rel_tol=1e-9)


def test_a_negative_first_min_sections_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        segment_flowpath([PipeRun(1.0)], max_section_m=1.0, first_min_sections=-1)


def _edge(result, pipe: int, valve: int = 0) -> float:
    return math.fsum(result.lengths_m[pipe][: result.valve_boundaries[pipe][valve]])


def test_a_valve_edge_sits_exactly_at_the_valve_position() -> None:
    result = segment_flowpath([PipeRun(10.0, valve_positions=(0.37,))], max_section_m=1.0)

    assert abs(_edge(result, 0) - 3.7) <= 1e-3
    assert math.isclose(math.fsum(result.lengths_m[0]), 10.0, rel_tol=1e-9)
    assert _worst(list(result.lengths_m[0])) <= 2.0


def test_two_valves_on_one_pipe_each_get_their_own_edge() -> None:
    result = segment_flowpath([PipeRun(12.0, valve_positions=(0.25, 0.8))], max_section_m=2.0)

    assert abs(_edge(result, 0, 0) - 3.0) <= 1e-3
    assert abs(_edge(result, 0, 1) - 9.6) <= 1e-3
    assert _worst(list(result.lengths_m[0])) <= 2.0


def test_a_valve_at_the_outlet_of_a_non_last_pipe_sits_on_its_last_boundary() -> None:
    result = segment_flowpath(
        [PipeRun(6.0, valve_positions=(1.0,)), PipeRun(6.0)], max_section_m=1.0)

    assert result.valve_boundaries[0] == (len(result.lengths_m[0]),)
    assert _worst(_sequence(result)) <= 2.0


def test_a_valve_at_the_very_outlet_of_the_flowpath_keeps_an_interior_edge() -> None:
    result = segment_flowpath([PipeRun(6.0, valve_positions=(1.0,))], max_section_m=1.0)

    assert result.valve_boundaries[0][0] < len(result.lengths_m[0])


def test_a_valve_edge_near_the_first_boundary_can_be_pushed_inward() -> None:
    result = segment_flowpath(
        [PipeRun(10.0, valve_positions=(0.02,))], max_section_m=1.0, min_first_valve_boundary=2)

    assert result.valve_boundaries[0][0] >= 2
    assert abs(_edge(result, 0) - 0.2) <= 1e-3


def test_a_valve_at_a_flowpath_outlet_into_a_junction_sits_on_the_last_boundary() -> None:
    # A source deck that OLGA 2022 ran holds such valves (SECTIONBOUNDARY = NSEGMENT of the
    # last pipe, flowpath ending at a junction); the outlet into a pressure node stays unproven.
    result = segment_flowpath(
        [PipeRun(6.0, valve_positions=(1.0,))], max_section_m=1.0, outlet_valve_on_end=True)

    assert result.valve_boundaries[0][0] == len(result.lengths_m[0])
