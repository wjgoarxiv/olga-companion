"""A failed run names its cause from OLGA's own stop message, using recorded real failures."""

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
