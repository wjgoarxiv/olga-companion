from __future__ import annotations

from pathlib import Path
from typing import Any


def run_status(ctx: Any, run_id: str) -> dict[str, Any]:
    with ctx._REGISTRY_LOCK:
        state = ctx._RUNS.get(run_id)
    if state is not None:
        return ctx._live_run_status(run_id, state)
    ctx.require_run_id(run_id)
    run_dir = ctx.sandbox_root() / "runs" / run_id
    try:
        record = ctx.load_run_record(run_dir)
    except FileNotFoundError as exc:
        raise ctx.UnknownRunError(run_id) from exc
    return ctx._status_from_receipt(record, run_dir)


def recent_runs(
    ctx: Any,
    limit: int = 20,
    source: str | None = None,
) -> list[dict[str, Any]]:
    source_path = str(Path(source).expanduser().resolve()) if source is not None else None
    records = ctx.recent_run_records(
        ctx.sandbox_root() / "runs",
        limit=limit,
        source_path=source_path,
    )
    history: list[dict[str, Any]] = []
    for record in records:
        run_dir = Path(str(record.pop("_run_dir")))
        if record.get("state") == "receipt_error":
            history.append(
                {
                    "run_id": record["run_id"],
                    "state": "receipt_error",
                    "exit_code": None,
                    "timed_out": False,
                    "cancelled": False,
                    "cancel_requested": False,
                    "ok": False,
                    "engine_failed": False,
                    "validation_valid": False,
                    "log_tail": "",
                    "run_dir": str(run_dir),
                    "command": [],
                    "detection": None,
                    "selection_id": None,
                    "outputs": [],
                    "failure": None,
                    "elapsed_ms": 0,
                    "recovered_from_receipt": False,
                    "recovery": "The persisted run receipt is invalid and cannot be recovered.",
                    "receipt_error": record["receipt_error"],
                    "solver_progress": ctx._indeterminate_solver_progress(),
                }
            )
        else:
            history.append(ctx._status_from_receipt(record, run_dir))
    return history


def run_capabilities(ctx: Any) -> dict[str, Any]:
    detection = ctx.detect_olga()
    broker_check = ctx.broker_capability() if detection.get("kind") == "engine" else None
    unsupported_native = (
        detection.get("kind") != "script"
        and str(detection.get("exe") or "").lower().endswith(".exe")
        and detection.get("kind") != "engine"
    )
    enabled = (
        bool(detection["detected"])
        and not unsupported_native
        and (broker_check is None or bool(broker_check["available"]))
    )
    if detection["detected"] and unsupported_native:
        reason = (
            "Detected native candidate is not a direct OLGA engine supported by the Explorer broker path."
        )
    elif detection["detected"] and broker_check is not None and not broker_check["available"]:
        reason = str(broker_check["reason"])
    elif detection["detected"]:
        reason = (
            f"OLGA executable detected via {detection['source']}: {detection['exe']} "
            "(availability only; runtime health is verified on each run). "
            "Runs still require validation and explicit approval."
        )
    else:
        reason = "No OLGA executable detected (checked OLGA_EXE_PATH and standard install paths)."
    return {"live_olga_run": {"enabled": enabled, "reason": reason}}
