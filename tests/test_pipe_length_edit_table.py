"""The edit table offers each pipe's length; a row goes through the same set_pipe_length plan as chat."""

from __future__ import annotations

from pathlib import Path

from test_case_edit_routes import _install, _plan, _publish, _row, _rows, ws  # noqa: F401

from olga_companion import case_edit_table
from olga_companion.case_lint import keyword_coverage
from olga_companion.case_spec_recovery import recover_case_spec

_FIXTURE = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"


def _owner_case(ws: Path, text: str | None = None) -> Path:  # noqa: F811
    case = ws / "owner.genkey"
    case.write_text(text or _FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return case


def test_an_app_case_offers_one_length_row_per_pipe(ws: Path) -> None:  # noqa: F811
    case = _install(ws, "valve-shut-in")
    spec = recover_case_spec(case)
    rows = _rows(case)
    for path in spec.flowpaths:
        for pipe in path.pipes:
            row = _row(rows, f"flowpaths.{path.label}.pipes.{pipe.label}.length_m")
            assert (row["target"], row["field"], row["unit"]) == (f"{path.label}/{pipe.label}", "length_m", "m")
            assert row["value"] == pipe.length
            assert row["op"] == {"op": "set_pipe_length", "flowpath": path.label, "pipe": pipe.label}
            assert row["keyword"] == "PIPE.LSEGMENT"


def test_an_app_case_length_row_publishes_a_new_copy(ws: Path) -> None:  # noqa: F811
    case = _install(ws, "valve-shut-in")
    before = case.read_bytes()
    rows = _rows(case)
    row = next(r for r in rows["rows"] if r["field"] == "length_m")
    plan = _plan(rows, [{**row["op"], "length_m": row["value"] * 1.5}]).json()
    assert plan["publishable"] is True, plan
    assert plan["semantic_diff"][0]["path"] == row["id"]
    assert _publish(plan).status_code == 200
    assert case.read_bytes() == before


def test_a_hand_written_case_offers_its_pipe_lengths(ws: Path) -> None:  # noqa: F811
    rows = _rows(_owner_case(ws))
    assert rows["marked"] is False
    lengths = {row["id"]: row for row in rows["rows"] if row["field"] == "length_m"}
    assert set(lengths) == {f"flowpaths.FLOWPATH_1.pipes.Pipe_{n}.length_m" for n in (1, 2, 3)}
    for n in (1, 2, 3):
        row = lengths[f"flowpaths.FLOWPATH_1.pipes.Pipe_{n}.length_m"]
        assert row["value"] == 100.0
        assert row["unit"] == "m"
        assert row["op"] == {"op": "set_pipe_length", "flowpath": "FLOWPATH_1", "pipe": f"Pipe_{n}"}
    # ENDTIME=24 h is not in seconds, so it has no row; the length rows stand on their own.
    assert "integration.end_time_s" not in {row["id"] for row in rows["rows"]}


def test_a_hand_written_case_length_row_publishes_and_moves_later_pipes(ws: Path) -> None:  # noqa: F811
    case = _owner_case(ws)
    before = case.read_bytes()
    rows = _rows(case)
    op = _row(rows, "flowpaths.FLOWPATH_1.pipes.Pipe_1.length_m")["op"]
    plan = _plan(rows, [{**op, "length_m": 120.0}]).json()
    assert plan["publishable"] is True, plan
    assert _publish(plan).status_code == 200
    published = (ws / plan["destination_rel"]).read_text(encoding="utf-8")
    assert "LSEGMENT=(24, 24, 24, 24, 24) m, XEND=120 m" in published
    assert "XEND=220 m" in published and "XEND=320 m" in published
    assert case.read_bytes() == before


def test_a_pipe_the_edit_cannot_change_gets_no_row(ws: Path) -> None:  # noqa: F811
    text = _FIXTURE.read_text(encoding="utf-8").replace(
        "LSEGMENT=(20, 20, 20, 20, 20) m, XEND=100 m", "LSEGMENT=(20, 20, 20, 20, 20) furlong, XEND=100 m"
    )
    ids = {row["id"] for row in _rows(_owner_case(ws, text))["rows"]}
    assert "flowpaths.FLOWPATH_1.pipes.Pipe_1.length_m" not in ids
    assert "flowpaths.FLOWPATH_1.pipes.Pipe_2.length_m" in ids


def test_coverage_counts_the_segment_lengths_as_a_table_key(ws: Path) -> None:  # noqa: F811
    case = _owner_case(ws)
    rows = case_edit_table.editable_rows(case)["rows"]
    assert "PIPE.LSEGMENT" in keyword_coverage(case, rows)["table"]
