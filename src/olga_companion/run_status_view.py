from __future__ import annotations

from pathlib import Path
from typing import Any

from .run_solver_findings import attach_solver_findings


def status_from_receipt_base(
    ctx: Any,
    record: dict[str, Any],
    run_dir: Path,
    state: str,
) -> dict[str, Any]:
    terminal = record["phase"] == "terminal"
    staged_case_name = record.get("staged_case_name")
    if terminal:
        persisted_progress = record.get("solver_progress")
        solver_progress = (
            ctx.copy.deepcopy(persisted_progress)
            if isinstance(persisted_progress, dict)
            else ctx._indeterminate_solver_progress(
                phase="terminal",
                liveness="terminal",
                out_name=(
                    f"{Path(staged_case_name).stem}.out"
                    if isinstance(staged_case_name, str)
                    else None
                ),
            )
        )
    elif isinstance(staged_case_name, str):
        recovered_running = state == "running"
        finalizing = state == "finalizing"
        solver_progress = ctx._solver_progress_for(
            run_dir,
            staged_case_name,
            phase=(
                "running"
                if recovered_running
                else "finalizing"
                if finalizing
                else "supervision_unknown"
            ),
            liveness=(
                "supervised"
                if recovered_running
                else "terminal"
                if finalizing
                else "supervision_unknown"
            ),
        )
    else:
        solver_progress = ctx._indeterminate_solver_progress(
            phase="supervision_unknown",
            liveness="supervision_unknown",
        )
    cancel_requested = False if terminal else ctx._receipt_cancel_requested(record, run_dir)
    status = {
        "run_id": record["run_id"],
        "state": state,
        "exit_code": record.get("exit_code") if terminal else None,
        "timed_out": bool(record.get("timed_out")),
        "cancelled": bool(record.get("cancelled")),
        "cancel_requested": cancel_requested,
        "ok": bool(record.get("ok")) if terminal else False,
        "engine_failed": bool(record.get("engine_failed")),
        "validation_valid": bool(record.get("validation_valid")),
        "log_tail": ctx.redact_log_paths(str(record.get("log_tail") or "")),
        "run_dir": str(run_dir),
        "command": record["command"],
        "detection": record.get("detection") or record["runtime"],
        "selection_id": record["selection_id"],
        "outputs": record["outputs"] if terminal else [],
        "failure": record.get("failure") if terminal else None,
        "elapsed_ms": int(record.get("elapsed_ms") or 0),
        "recovered_from_receipt": True,
        "recovery": None,
        "solver_progress": solver_progress,
        "collection_pending": state == "finalizing",
    }
    attach_solver_findings(status)
    return status


def receipt_cancel_requested(ctx: Any, record: dict[str, Any], run_dir: Path) -> bool:
    broker_run = record.get("broker_run")
    if not isinstance(broker_run, dict):
        return False
    cancel_name = broker_run.get("cancel_name")
    if not isinstance(cancel_name, str) or Path(cancel_name).name != cancel_name:
        return False
    try:
        return (run_dir / cancel_name).is_file()
    except OSError:
        return False
