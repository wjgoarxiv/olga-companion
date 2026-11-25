"""A failed run names its cause from OLGA's own stop message, using short hand-written logs with that wording."""

from __future__ import annotations

from pathlib import Path

from olga_companion.run_solver_findings import attach_solver_findings
from olga_companion.run_stop_reason import explain_stop

FIXTURES = Path(__file__).parent / "fixtures" / "run_failures"


def _read(name: str, file: str) -> str:
    return (FIXTURES / name / file).read_text(encoding="utf-8", errors="replace")


def test_pressure_above_the_table_at_a_node_stops_at_zero() -> None:
    reason = explain_stop(_read("pressure_above", "case.out"), _read("pressure_above", "run.log"), 66)
    assert reason["code"] == "pressure_above_table"
    assert reason["stopped_at_s"] == 0.0
    assert reason["pressure_bara"] == 900.0
    assert reason["temperature_c"] == 40.0
    assert reason["where"] == "NODE INLET"
    assert reason["exit_code"] == 66
    assert reason["exit_message"] == "pressure above"


def test_pressure_below_the_table_mid_run_names_the_section() -> None:
    reason = explain_stop(_read("pressure_below_mid_run", "case.out"), _read("pressure_below_mid_run", "run.log"), 65)
    assert reason["code"] == "pressure_below_table"
    assert reason["stopped_at_s"] == 985.6116154
    assert reason["pressure_bara"] == 0.48789
    assert reason["temperature_c"] == 24.734
    assert reason["where"] == "FLOWPATH=MAIN, PIPE=DOWNSTREAM, SECTION=9"


def test_an_unknown_stop_says_unknown_and_keeps_the_last_messages() -> None:
    log = "line one\n**** OLGA stopped with exit message 'something new' (77) ****\n"
    reason = explain_stop("", log, 77)
    assert reason["code"] == "unknown"
    assert reason["exit_message"] == "something new"
    assert reason["last_lines"][-1].startswith("**** OLGA stopped")


def test_last_lines_carry_no_private_paths() -> None:
    log = "INPUT FILE : C:\\Users\\someone\\AppData\\Local\\x\\case.genkey\nTHE OLGA SIMULATION ABORTED AT TIME 1.5 SECONDS.\n"
    reason = explain_stop("", log, 1)
    joined = "\n".join(reason["last_lines"])
    assert "someone" not in joined and "Users" not in joined
    assert reason["stopped_at_s"] == 1.5


def test_a_failed_status_carries_the_stop_reason(tmp_path: Path) -> None:
    out = tmp_path / "case.out"
    out.write_text(_read("pressure_below_mid_run", "case.out"), encoding="utf-8")
    status = {
        "state": "failed", "exit_code": 65, "log_tail": _read("pressure_below_mid_run", "run.log"),
        "outputs": [{"name": "case.out", "suffix": ".out", "path": str(out)}],
    }
    attach_solver_findings(status)
    assert status["stop_reason"]["code"] == "pressure_below_table"


def test_a_completed_status_has_no_stop_reason() -> None:
    status = {"state": "completed", "exit_code": 0, "log_tail": "", "outputs": []}
    attach_solver_findings(status)
    assert status["stop_reason"] is None


# N3: each stop carries the OLGA line it was read from and, when OLGA names one, the place in
# the case to look at. A stop the reader does not recognise points nowhere.
ABORT_LOG = Path(__file__).parent / "fixtures" / "out" / "olga_abort_run.log"


def test_a_node_stop_cites_its_line_and_points_at_the_node() -> None:
    reason = explain_stop(_read("pressure_above", "case.out"), _read("pressure_above", "run.log"), 66)
    assert reason["evidence"] == "PRESSURE ABOVE TABLE VALUES (P = 900 bara, T = 40 C)"
    assert reason["pointer"] == {"kind": "node", "label": "INLET"}


def test_a_pipe_stop_points_at_the_pipe_and_section() -> None:
    reason = explain_stop(_read("pressure_below_mid_run", "case.out"), _read("pressure_below_mid_run", "run.log"), 65)
    assert reason["evidence"] == "PRESSURE BELOW TABLE VALUES (P = 0.48789 bara, T = 24.734 C)"
    assert reason["pointer"] == {"kind": "pipe", "flowpath": "MAIN", "label": "DOWNSTREAM", "section": 9}


def test_a_temperature_stop_reads_the_same_way() -> None:
    # Synthetic: the node stop with OLGA's temperature wording in place of the pressure one.
    out = _read("pressure_above", "case.out").replace("PRESSURE ABOVE", "TEMPERATURE BELOW")
    reason = explain_stop(out, "", 64)
    assert reason["code"] == "temperature_below_table"
    assert reason["evidence"].startswith("TEMPERATURE BELOW TABLE VALUES")
    assert reason["pointer"] == {"kind": "node", "label": "INLET"}


def test_a_rejected_input_points_at_the_component_keyword_and_key() -> None:
    log = ABORT_LOG.read_text(encoding="utf-8", errors="replace")
    reason = explain_stop("", log, 18)
    assert reason["code"] == "input_rejected"
    assert reason["evidence"] == "BRANCH: TagsFrom component with LABEL or NUMBER 1 as referred to in key FLUID is not found."
    assert reason["pointer"] == {"kind": "keyword", "component": "FLOWPATH_1", "keyword": "BRANCH", "key": "FLUID"}
    assert "Jordan" not in reason["evidence"]


def test_an_unknown_stop_cites_the_exit_line_and_points_nowhere() -> None:
    log = "line one\n**** OLGA stopped with exit message 'something new' (77) ****\n"
    reason = explain_stop("", log, 77)
    assert reason["evidence"] == "**** OLGA stopped with exit message 'something new' (77) ****"
    assert reason["pointer"] is None


def test_a_place_the_reader_cannot_parse_points_nowhere() -> None:
    out = "PRESSURE ABOVE TABLE VALUES (P = 900 bara, T = 40 C)\nREPORTED IN SOMETHING ODD 7\n"
    reason = explain_stop(out, "", 66)
    assert reason["where"] == "SOMETHING ODD 7"
    assert reason["pointer"] is None


def test_the_evidence_line_carries_no_private_path() -> None:
    out = "PRESSURE ABOVE TABLE VALUES (P = 900 bara, T = 40 C) C:\\Users\\someone\\case.genkey\n"
    reason = explain_stop(out, "", 66)
    assert "someone" not in reason["evidence"]
