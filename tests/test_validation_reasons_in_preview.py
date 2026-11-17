"""A failed checker says why in the run preview.

Bug report 2026-11-15 (0.1.8): an existing .genkey showed only "검사기: 실패" in the
run preview, with no reason, so the user could not tell what to fix.
"""

from __future__ import annotations

from pathlib import Path

from olga_companion import runner


def test_a_failed_check_lists_its_errors(tmp_path: Path) -> None:
    case = tmp_path / "broken.genkey"
    case.write_text("CASE AUTHOR=\"x\"\n", encoding="utf-8")

    result = runner._validate_case(case)

    assert result["valid"] is False
    assert result["problems"], "the preview needs at least one reason"
    assert all(line.startswith("[") for line in result["problems"])


def test_a_checker_that_could_not_run_still_gives_a_reason() -> None:
    problems = runner._validation_problems(
        {"exit_code": 1, "stdout": "", "stderr": "Error: file not found: x.genkey\n"}
    )
    assert problems == ["Error: file not found: x.genkey"]


def test_a_passed_check_has_no_problems(tmp_path: Path) -> None:
    assert runner._validation_problems({"exit_code": 0, "stdout": "No issues found.", "stderr": ""}) == []
