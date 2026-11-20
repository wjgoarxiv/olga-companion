"""Sweep summary rows: per-case params, run truth, end-of-run outputs or honest nulls."""
from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import sweep_summary
from olga_companion.genkey_static import OlgaInputError
from olga_companion import runner as runner_module

FIXTURES = Path(__file__).parent / "fixtures" / "results"


def _cases() -> list[dict]:
    return [
        {
            "index": 0,
            "path": "case_00.genkey",
            "params": [{"path": "INTEGRATION.ENDTIME", "value": "60 s"}],
            "run_id": "run-1",
            "state": "completed",
            "ok": True,
        },
        {
            "index": 1,
            "path": "case_01.genkey",
            "params": [{"path": "INTEGRATION.ENDTIME", "value": "120 s"}],
            "run_id": None,
            "state": "planned",
            "ok": False,
        },
        {
            "index": 2,
            "path": "case_02.genkey",
            "params": [{"path": "INTEGRATION.ENDTIME", "value": "300 s"}],
            "run_id": "run-3",
            "state": "failed",
            "ok": False,
        },
    ]


def _run_status(run_id: str) -> dict:
    if run_id == "run-1":
        return {
            "state": "completed",
            "ok": True,
            "outputs": [
                {
                    "name": "sweep_case_1.tpl",
                    "path": str(FIXTURES / "sweep_case_1.tpl"),
                    "suffix": ".tpl",
                }
            ],
        }
    if run_id == "run-3":
        return {"state": "failed", "ok": False, "outputs": []}
    raise runner_module.UnknownRunError(run_id)


def _series(tpl_path: str, variable: str) -> dict:
    if variable in ("PT", "TM"):
        return {
            "path": tpl_path,
            "variable": variable,
            "unit": "PA" if variable == "PT" else "C",
            "time": [0.0, 60.0],
            "values": [101325.0, 202650.0] if variable == "PT" else [20.0, 40.0],
            "time_unit": "s",
        }
    raise OlgaInputError(f"Could not read a series for {variable!r}.")


def test_summary_rows_match_case_count_with_honest_nulls() -> None:
    rows = sweep_summary.summarize_cases(
        _cases(), run_status_fn=_run_status, series_fn=_series
    )
    assert len(rows) == 3

    finished = rows[0]
    assert finished["run_id"] == "run-1"
    assert finished["params"] == [{"path": "INTEGRATION.ENDTIME", "value": "60 s"}]
    assert finished["outputs"]["PT"]["value"] == pytest.approx(202650.0)
    assert finished["outputs"]["PT"]["unit"] == "PA"
    assert finished["outputs"]["HOL"]["value"] is None
    assert finished["outputs"]["HOL"]["reason"]
    assert finished["outputs"]["LIQC"]["value"] is None
    assert finished["outputs"]["LIQC"]["reason"]

    planned = rows[1]
    assert all(cell["value"] is None for cell in planned["outputs"].values())
    assert all(cell["reason"] for cell in planned["outputs"].values())

    failed = rows[2]
    assert failed["state"] == "failed"
    assert all(cell["value"] is None for cell in failed["outputs"].values())


def test_unknown_child_run_is_listed_not_fabricated() -> None:
    cases = [
        {
            "index": 0,
            "path": "case_00.genkey",
            "params": [],
            "run_id": "run-gone",
            "state": "completed",
            "ok": True,
        }
    ]

    def _gone(run_id: str) -> dict:
        raise runner_module.UnknownRunError(run_id)

    (row,) = sweep_summary.summarize_cases(
        cases, run_status_fn=_gone, series_fn=_series
    )
    assert row["state"] == "failed"
    assert all(cell["value"] is None for cell in row["outputs"].values())
    assert all(cell["reason"] for cell in row["outputs"].values())


def _three_done() -> tuple[list[dict], callable, callable]:
    ends = {"run-a": (100.0, 20.0), "run-b": (130.0, 18.5), "run-c": (90.0, 21.0)}
    cases = [{"index": i, "params": [], "run_id": run_id, "state": "completed", "ok": True}
             for i, run_id in enumerate(ends)] + [{"index": 3, "params": [], "run_id": "run-x", "state": "failed", "ok": False}]

    def status(run_id: str) -> dict:
        if run_id == "run-x":
            return {"state": "failed", "ok": False, "outputs": []}
        return {"state": "completed", "ok": True, "outputs": [{"name": f"{run_id}.tpl", "path": f"{run_id}.tpl", "suffix": ".tpl"}]}

    def series(tpl_path: str, variable: str) -> dict:
        pt, tm = ends[tpl_path.removesuffix(".tpl")]
        if variable == "PT":
            return {"unit": "bara", "time": [0.0, 60.0], "values": [1.0, pt], "time_unit": "s"}
        if variable == "TM":
            return {"unit": "C", "time": [0.0, 60.0], "values": [1.0, tm], "time_unit": "s"}
        raise OlgaInputError("no series")

    return cases, status, series


def test_each_case_carries_its_change_from_the_base_case() -> None:
    # 0.1.20 row 8: the base case is the first case; change = end value - base end value.
    cases, status, series = _three_done()
    rows = sweep_summary.summarize_cases(cases, run_status_fn=status, series_fn=series)
    assert [row["outputs"]["PT"]["change"] for row in rows[:3]] == [0.0, 30.0, -10.0]
    assert [row["outputs"]["TM"]["change"] for row in rows[:3]] == [0.0, -1.5, 1.0]
    assert rows[0]["outputs"]["PT"]["change_reason"] is None


def test_no_change_is_invented_for_a_missing_value_or_base() -> None:
    cases, status, series = _three_done()
    rows = sweep_summary.summarize_cases(cases, run_status_fn=status, series_fn=series)
    failed = rows[3]["outputs"]["PT"]
    assert failed["change"] is None and failed["change_reason"] == "run failed"
    assert rows[1]["outputs"]["HOL"]["change"] is None
    assert rows[1]["outputs"]["HOL"]["change_reason"] == "HOL series is empty" or "not available" in rows[1]["outputs"]["HOL"]["change_reason"]
    # The base itself failed: no case has a change, and each says why.
    rows = sweep_summary.summarize_cases([cases[3], *cases[:3]], run_status_fn=status, series_fn=series)
    assert all(row["outputs"]["PT"]["change"] is None for row in rows)
    assert rows[1]["outputs"]["PT"]["change_reason"] == "base case has no value"


def test_a_change_across_different_units_is_refused() -> None:
    cases, status, series = _three_done()

    def mixed(tpl_path: str, variable: str) -> dict:
        cell = series(tpl_path, variable)
        return {**cell, "unit": "Pa"} if tpl_path == "run-b.tpl" and variable == "PT" else cell

    rows = sweep_summary.summarize_cases(cases, run_status_fn=status, series_fn=mixed)
    assert rows[1]["outputs"]["PT"]["change"] is None
    assert rows[1]["outputs"]["PT"]["change_reason"] == "unit differs from the base case"
