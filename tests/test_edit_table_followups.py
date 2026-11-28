"""Follow-ups from the 2026-11-29 review of the edit-table pipe length work."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_case_edit_routes import _plan, _rows, ws  # noqa: F401

from olga_companion import case_edit_table, owner_pipe_length
from olga_companion.case_compiler_toolkit import validator_count, validator_lines, validator_warnings
from olga_companion.case_lint import keyword_coverage

_FIXTURE = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"


def _owner_case(ws: Path, text: str | None = None) -> Path:  # noqa: F811
    case = ws / "owner.genkey"
    case.write_text(text or _FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return case


def _report(errors: int, warnings: int) -> str:
    lines = ["Validation Report: x.genkey", "=" * 40, f"ERRORS:   {errors}", f"WARNINGS: {warnings}", "INFO:     0", ""]
    if errors:
        lines += ["ERRORS", "------"]
        for n in range(errors):
            lines += [f"[X014] PIPE 'P{n}' in 'L' spans 120 m between its end points but its LSEGMENT sum is 100 m",
                      "       Location : L / PIPE P", "       Suggestion: Change LSEGMENT", ""]
    if warnings:
        lines += ["WARNINGS", "--------"]
        for n in range(warnings):
            lines += [f"[P008] Neighbouring sections in 'L' differ by 3.00x (P{n} 60 -> P{n + 1} 20)", ""]
    return "\n".join(lines) + "\n"


def test_the_report_counts_and_lines_are_read_per_section() -> None:
    report = _report(errors=3, warnings=10)
    assert validator_count(report, "ERRORS") == 3
    assert validator_count(report, "WARNINGS") == 10
    assert validator_count("No report", "WARNINGS") == 0
    assert len(validator_warnings(report)) == 8
    errors = validator_lines(report, "ERRORS")
    assert [line[:16] for line in errors] == ["[X014] PIPE 'P0'", "[X014] PIPE 'P1'", "[X014] PIPE 'P2'"]


def test_a_refused_owner_edit_names_every_validator_error(ws: Path) -> None:  # noqa: F811
    # Pipe_1 drawn 120 m long but meshed 100 m: Pipe_1 and Pipe_2 both fail X014, so OLGA would refuse the case.
    case = _owner_case(ws, _FIXTURE.read_text(encoding="utf-8").replace("XEND=100 m", "XEND=120 m"))
    rows = _rows(case)
    plan = _plan(rows, [{"op": "set_pipe_length", "flowpath": "FLOWPATH_1", "pipe": "Pipe_3", "length_m": 110.0}]).json()
    assert plan["publishable"] is False, plan
    text = json.dumps(plan)
    assert "[X014] PIPE 'Pipe_1'" in text and "[X014] PIPE 'Pipe_2'" in text, plan


def test_a_plan_reports_the_full_warning_count(ws: Path) -> None:  # noqa: F811
    plan = _plan(
        _rows(_owner_case(ws)),
        [{"op": "set_pipe_length", "flowpath": "FLOWPATH_1", "pipe": "Pipe_1", "length_m": 300.0}],
    ).json()
    assert plan["publishable"] is True, plan
    assert plan["validation"]["warning_count"] == len(plan["validation"]["warnings"]) == 1


def test_the_length_rows_parse_the_file_once(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    text = _FIXTURE.read_text(encoding="utf-8")
    calls = []
    real = owner_pipe_length._statements
    monkeypatch.setattr(owner_pipe_length, "_statements", lambda t: calls.append(1) or real(t))
    found = owner_pipe_length.owner_pipe_lengths(text)
    assert found == [("FLOWPATH_1", f"Pipe_{n}", 100.0) for n in (1, 2, 3)]
    assert len(calls) == 1


def test_coverage_counts_the_end_points_a_length_row_moves(ws: Path) -> None:  # noqa: F811
    case = _owner_case(ws)
    coverage = keyword_coverage(case, case_edit_table.editable_rows(case)["rows"])
    assert "PIPE.XEND" in coverage["table"], coverage
    assert "PIPE.XEND" not in coverage["fixed"] and "PIPE.XEND" not in coverage["sweep"]
    # The fixture has no PIPE LENGTH key, so the table does not claim one.
    assert "PIPE.LENGTH" not in coverage["table"]
