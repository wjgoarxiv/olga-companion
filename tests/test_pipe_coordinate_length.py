"""A pipe given by end coordinates must be as long as its LSEGMENT sum (X014)."""
from __future__ import annotations

from pathlib import Path

from olga_companion import genkey_static

FIXTURE = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"


def _x014(tmp_path: Path, text: str) -> list[str]:
    case = tmp_path / "c.genkey"
    case.write_text(text, encoding="utf-8")
    report = genkey_static.run_tool("validator", [str(case)]).stdout
    assert "Validation Report" in report
    return [line for line in report.splitlines() if "X014" in line]


def test_the_shipped_example_has_matching_lengths(tmp_path: Path) -> None:
    assert _x014(tmp_path, FIXTURE.read_text(encoding="utf-8")) == []


def test_a_moved_end_point_without_new_segments_is_flagged(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace("XEND=100 m", "XEND=120 m")
    lines = _x014(tmp_path, text)
    # Pipe_1 is now 120 m long by coordinates, Pipe_2 80 m; both still sum to 100 m.
    assert len(lines) == 2
    assert "Pipe_1" in lines[0] and "120" in lines[0] and "100" in lines[0]
    assert "Pipe_2" in lines[1] and "80" in lines[1]


def test_a_moved_end_point_is_an_error_because_olga_refuses_the_case(tmp_path: Path) -> None:
    # OLGA 2022.1 stops such a case before time 0: "The total length of segments
    # (LSEGMENT sum: 100) does not match the pipe length (LENGTH: 120) [tolerance 1%]".
    case = tmp_path / "c.genkey"
    case.write_text(FIXTURE.read_text(encoding="utf-8").replace("XEND=100 m", "XEND=120 m"), encoding="utf-8")
    result = genkey_static.run_tool("validator", [str(case)])
    errors = result.stdout.split("\nERRORS\n", 1)[1].split("\nWARNINGS\n", 1)[0]
    assert result.exit_code == 1
    assert "[X014]" in errors


def test_a_consistent_length_change_passes(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace(
        "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=100 m",
        "LSEGMENT=(24, 24, 24, 24, 24) m, XEND=120 m",
    )
    text = text.replace("XEND=200 m", "XEND=220 m").replace("XEND=300 m", "XEND=320 m")
    assert _x014(tmp_path, text) == []


def test_units_and_a_sloped_pipe_are_measured_in_3d(tmp_path: Path) -> None:
    text = '''OPTIONS TEMPERATURE=ADIABATIC
NETWORKCOMPONENT TYPE=FLOWPATH, TAG=FLOWPATH_1
 PARAMETERS LABEL=LINE
 GEOMETRY LABEL="G", XSTART=0 m, YSTART=0 m, ZSTART=0 m
 PIPE LABEL="P1", WALL=W, NSEGMENT=2, LSEGMENT=(2.5, 2.5) km, XEND=3000 m, YEND=4000 m, ZEND=0 m, DIAMETER=0.2 m
 PIPE LABEL="P2", WALL=W, NSEGMENT=1, LSEGMENT=(10) m, XEND=3000 m, YEND=4000 m, ZEND=-10 m, DIAMETER=0.2 m
ENDNETWORKCOMPONENT
ENDCASE
'''
    assert _x014(tmp_path, text) == []


def test_pipes_without_coordinates_are_not_checked(tmp_path: Path) -> None:
    text = '''OPTIONS TEMPERATURE=ADIABATIC
NETWORKCOMPONENT TYPE=FLOWPATH, TAG=FLOWPATH_1
 PARAMETERS LABEL=LINE
 GEOMETRY LABEL="G"
 PIPE LABEL="P1", WALL=W, NSEGMENT=2, LSEGMENT=(50, 50) m, LENGTH=100 m, ELEVATION=0 m, DIAMETER=0.2 m
 PIPE LABEL="P2", WALL=W, NSEGMENT=1, LSEGMENT=(10) m, XEND=500 m, YEND=0 m, DIAMETER=0.2 m
ENDNETWORKCOMPONENT
ENDCASE
'''
    # P2's start point is unknown after a pipe given by LENGTH, so nothing is claimed.
    assert _x014(tmp_path, text) == []
