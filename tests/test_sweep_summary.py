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
