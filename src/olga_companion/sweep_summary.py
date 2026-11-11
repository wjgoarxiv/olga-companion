"""End-of-run sweep summary: per-case params, run truth, and key outputs.

Read-only. Every output cell is either a measured end-of-run value or an
explicit null with a reason — never a fabricated number.
"""
from __future__ import annotations

from typing import Any, Callable

from . import results, runner, sweep_execution

SUMMARY_VARIABLES: tuple[str, ...] = ("PT", "TM", "HOL", "LIQC")


def _null_cell(reason: str) -> dict[str, Any]:
    return {"value": None, "unit": None, "time": None, "time_unit": None, "reason": reason}


def _blank_outputs(reason: str) -> dict[str, dict[str, Any]]:
    return {variable: _null_cell(reason) for variable in SUMMARY_VARIABLES}


def _first_tpl(outputs: Any) -> str | None:
    if not isinstance(outputs, list):
        return None
    for entry in outputs:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or ""
        suffix = str(entry.get("suffix") or "")
        path = entry.get("path")
        if (suffix == ".tpl" or str(name).lower().endswith(".tpl")) and isinstance(path, str) and path:
            return path
    return None


def _read_outputs(
    tpl_path: str,
    series_fn: Callable[[str, str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    cells: dict[str, dict[str, Any]] = {}
    for variable in SUMMARY_VARIABLES:
        try:
            series = series_fn(tpl_path, variable)
        except Exception as exc:  # noqa: BLE001 — any loader failure is a null+reason, never fatal
            cells[variable] = _null_cell(f"{variable} not available: {exc}")
            continue
        values = series.get("values") if isinstance(series, dict) else None
        times = series.get("time") if isinstance(series, dict) else None
        if not isinstance(values, list) or not values:
            cells[variable] = _null_cell(f"{variable} series is empty")
            continue
        end_time = times[-1] if isinstance(times, list) and times else None
        cells[variable] = {
            "value": values[-1],
            "unit": series.get("unit"),
            "time": end_time,
            "time_unit": series.get("time_unit"),
            "position": series.get("position"),
            "reason": None,
        }
    return cells


def summarize_cases(
    cases: list[dict[str, Any]],
    *,
    run_status_fn: Callable[[str], dict[str, Any]] = runner.run_status,
    series_fn: Callable[[str, str], dict[str, Any]] = results.variable_series,
    unknown_run_error: type[Exception] = runner.UnknownRunError,
) -> list[dict[str, Any]]:
    """Summarize already-computed status-format sweep cases. No launches, no approvals."""
    rows: list[dict[str, Any]] = []
    for case in cases:
        run_id = case.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            rows.append(
                {
                    "index": case.get("index"),
                    "params": case.get("params", []),
                    "run_id": None,
                    "state": case.get("state", "planned"),
                    "ok": False,
                    "tpl": None,
                    "outputs": _blank_outputs("case has no run yet"),
                }
            )
            continue
        if case.get("start_error"):
            rows.append(
                {
                    "index": case.get("index"),
                    "params": case.get("params", []),
                    "run_id": run_id,
                    "state": "failed",
                    "ok": False,
                    "tpl": None,
                    "outputs": _blank_outputs(str(case["start_error"])),
                }
            )
            continue
        try:
            run = run_status_fn(run_id)
        except unknown_run_error:
            rows.append(
                {
                    "index": case.get("index"),
                    "params": case.get("params", []),
                    "run_id": run_id,
                    "state": "failed",
                    "ok": False,
                    "tpl": None,
                    "outputs": _blank_outputs("child run disappeared"),
                }
            )
            continue
        run_state = str(run.get("state", "unknown"))
        if run_state != "completed" or not run.get("ok"):
            rows.append(
                {
                    "index": case.get("index"),
                    "params": case.get("params", []),
                    "run_id": run_id,
                    "state": run_state,
                    "ok": False,
                    "tpl": None,
                    "outputs": _blank_outputs(f"run {run_state}"),
                }
            )
            continue
        tpl_path = _first_tpl(run.get("outputs"))
        if tpl_path is None:
            rows.append(
                {
                    "index": case.get("index"),
                    "params": case.get("params", []),
                    "run_id": run_id,
                    "state": run_state,
                    "ok": True,
                    "tpl": None,
                    "outputs": _blank_outputs("run has no .tpl output"),
                }
            )
            continue
        rows.append(
            {
                "index": case.get("index"),
                "params": case.get("params", []),
                "run_id": run_id,
                "state": run_state,
                "ok": True,
                "tpl": tpl_path,
                "outputs": _read_outputs(tpl_path, series_fn),
            }
        )
    return rows


def summarize_sweep(
    sweep_id: str,
    *,
    status_fn: Callable[[str], dict[str, Any]] = sweep_execution.sweep_status,
) -> dict[str, Any]:
    """Read-only summary for a finished (or running) sweep."""
    status = status_fn(sweep_id)
    rows = summarize_cases(status.get("cases", []))
    return {"sweep_id": sweep_id, "case_count": len(rows), "rows": rows}
