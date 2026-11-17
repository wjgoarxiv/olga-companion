from __future__ import annotations

import time
from typing import Any

from . import runner
from .sweep_selection import SweepCaseState, SweepState


def cancel_state(state: SweepState) -> None:
    with state.lock:
        if state.started_monotonic is None:
            state.cancelled = True
            state.finished_monotonic = state.finished_monotonic or time.monotonic()
            return
        run_ids = [case.run_id for case in state.cases if case.run_id]
    cancel_requested = False
    for run_id in run_ids:
        try:
            status = runner.run_status(run_id)
            if status["state"] in {"running", "supervision_unknown"}:
                runner.cancel_run(run_id)
                cancel_requested = True
        except runner.UnknownRunError:
            continue
    if cancel_requested:
        with state.lock:
            state.cancelled = True


def case_status(case: SweepCaseState, sweep_cancelled: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": case.index,
        "path": str(case.path),
        "valid": case.valid,
        "validation_errors": case.validation_errors,
        "params": case.params,
        "run_id": case.run_id,
        "pvt_files": case.pvt_files,
        "ok": False,
        "cancel_requested": False,
        "solver_progress": runner._indeterminate_solver_progress(),
    }
    if case.start_error:
        return {**payload, "state": "failed", "error": case.start_error}
    if case.run_id is None:
        return {**payload, "state": "planned"}
    try:
        status = runner.run_status(case.run_id)
    except runner.UnknownRunError:
        return {**payload, "state": "failed", "error": "child run disappeared"}
    return {
        **payload,
        "state": status["state"],
        "ok": bool(status["ok"]),
        "exit_code": status["exit_code"],
        "engine_failed": status["engine_failed"],
        "elapsed_ms": status["elapsed_ms"],
        "log_tail": status["log_tail"],
        "cancel_requested": bool(status.get("cancel_requested")),
        "solver_progress": status["solver_progress"],
    }


def aggregate_state(cases: list[dict[str, Any]], started: bool, cancelled: bool) -> str:
    states = {str(case["state"]) for case in cases}
    if not started:
        return "cancelled" if cancelled else "planned"
    if "running" in states:
        return "running"
    if "finalizing" in states:
        return "finalizing"
    if "supervision_unknown" in states:
        return "supervision_unknown"
    if states == {"completed"}:
        return "completed"
    if cancelled:
        return "cancelled"
    if "timed_out" in states:
        return "timed_out"
    if "cancelled" in states:
        return "cancelled"
    return "failed"
