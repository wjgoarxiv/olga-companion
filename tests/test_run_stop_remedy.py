"""0.1.20 row 6: a stopped run points at the edit-table row it names, never at a value."""

from __future__ import annotations

from olga_companion.run_stop_remedy import remedy_for

ROWS = [
    {"id": "integration.end_time_s", "op": {"op": "set_integration"}, "field": "end_time_s", "target": "ENDTIME"},
    {"id": "integration.max_dt_s", "op": {"op": "set_time_step"}, "field": "max_dt_s", "target": "MAXDT"},
    {"id": "flowpaths.MAIN.pipes.P1.roughness_m", "op": {"op": "set_pipe_roughness", "flowpath": "MAIN", "pipe": "P1"},
     "field": "roughness_m", "target": "MAIN/P1"},
    {"id": "flowpaths.MAIN.pipes.P2.roughness_m", "op": {"op": "set_pipe_roughness", "flowpath": "MAIN", "pipe": "P2"},
     "field": "roughness_m", "target": "MAIN/P2"},
]
COVERAGE = {"table": ["INTEGRATION.ENDTIME", "INTEGRATION.MAXDT", "PIPE.ROUGHNESS"],
            "sweep": ["SOURCE.TEMPERATURE"], "fixed": ["PIPE.LENGTH"]}


def _rejected(component: str, keyword: str, key: str) -> dict:
    return {"code": "input_rejected", "pointer": {"kind": "keyword", "component": component, "keyword": keyword, "key": key}}


def test_a_rejected_key_in_the_table_points_at_its_row() -> None:
    assert remedy_for(_rejected("INTEGRATION", "INTEGRATION", "MAXDT"), ROWS, COVERAGE) == {
        "row_id": "integration.max_dt_s", "reason_key": "row"}


def test_a_rejected_pipe_key_points_at_the_named_pipe() -> None:
    assert remedy_for(_rejected("P2", "PIPE", "ROUGHNESS"), ROWS, COVERAGE)["row_id"] == "flowpaths.MAIN.pipes.P2.roughness_m"


def test_two_rows_and_no_name_match_points_nowhere() -> None:
    assert remedy_for(_rejected("X9", "PIPE", "ROUGHNESS"), ROWS, COVERAGE) == {"row_id": None, "reason_key": "ambiguous"}


def test_a_key_the_table_cannot_change_says_why() -> None:
    assert remedy_for(_rejected("S", "SOURCE", "TEMPERATURE"), ROWS, COVERAGE) == {"row_id": None, "reason_key": "sweep_only"}
    assert remedy_for(_rejected("P1", "PIPE", "LENGTH"), ROWS, COVERAGE) == {"row_id": None, "reason_key": "fixed"}
    assert remedy_for(_rejected("P1", "PIPE", "NSEGMENT"), ROWS, COVERAGE) == {"row_id": None, "reason_key": "not_editable"}


def test_table_range_unknown_and_missing_stops_point_nowhere() -> None:
    for code in ("pressure_above_table", "temperature_below_table"):
        assert remedy_for({"code": code, "pointer": {"kind": "node", "label": "N1"}}, ROWS, COVERAGE) == {
            "row_id": None, "reason_key": "table_range"}
    assert remedy_for({"code": "unknown", "pointer": None}, ROWS, COVERAGE) == {"row_id": None, "reason_key": "unknown"}
    assert remedy_for(None, ROWS, COVERAGE) == {"row_id": None, "reason_key": "unknown"}
    assert remedy_for({"code": "solver_stalled"}, ROWS, COVERAGE) == {"row_id": None, "reason_key": "unknown"}
