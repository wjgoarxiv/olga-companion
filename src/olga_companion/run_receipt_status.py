from __future__ import annotations

from pathlib import Path
from typing import Any


_INTERRUPTED_FAILURE = {
    "code": "run_interrupted",
    "title": "Run stopped when the app closed",
    "detail": (
        "OLGA Companion closed or stopped while OLGA was running this case, "
        "so OLGA was stopped with it."
    ),
    "action": "Run the case again. Keep OLGA Companion open until the run finishes.",
    "auto_retry_safe": False,
}


def _close_orphaned_native_run(
    ctx: Any, record: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    """A native run whose sidecar is gone ended with it; record how it ended."""
    with ctx._RECEIPT_RECOVERY_LOCK:
        current = ctx.load_run_record(run_dir)
        if current["phase"] == "terminal":
            return ctx._status_from_receipt_base(current, run_dir, str(current["state"]))
        staged_case_name = str(current.get("staged_case_name") or ctx.FIXED_CASE_NAME)
        started_wall_ns = int(current["native_run"].get("started_wall_ns") or 0)
        try:
            native_completion = ctx.qualify_native_completion(
                run_dir, staged_case_name, started_wall_ns
            )
            outputs = ctx.collect_outputs(
                run_dir,
                companions=current.get("companions"),
                started_wall_ns=started_wall_ns,
            )
        except (PermissionError, OSError):
            return ctx._status_from_receipt_base(current, run_dir, "finalizing")
        completed = bool(native_completion["ok"])
        state = "completed" if completed else "failed"
        current.update(
            {
                "phase": "terminal",
                "state": state,
                "failure": None if completed else dict(_INTERRUPTED_FAILURE),
                "outputs": outputs,
                "ok": completed and bool(current.get("validation_valid")),
                "engine_failed": not completed,
                "native_completion": native_completion,
                "solver_progress": ctx._solver_progress_for(
                    run_dir, staged_case_name, phase="terminal", liveness="terminal"
                ),
            }
        )
        if current["timestamps"].get("finished_at") is None:
            current["timestamps"]["finished_at"] = ctx._utc_now()
        try:
            ctx.write_run_record(run_dir, current)
        except (OSError, ctx.RunRecordError):
            return ctx._status_from_receipt_base(current, run_dir, "finalizing")
        return ctx._status_from_receipt_base(current, run_dir, state)


_BROKER_GONE_FAILURE = {
    "code": "run_interrupted",
    "title": "Run stopped before OLGA finished",
    "detail": (
        "The helper that ran OLGA stopped (for example, the PC restarted or it was ended), "
        "so OLGA stopped with it."
    ),
    "action": "Run the case again and keep the PC on until the run finishes.",
    "auto_retry_safe": False,
}
# A broker checks for a cancel before it starts OLGA and writes a status at once when it does;
# a cancel this old with still no status means OLGA was never started for this request.
_CANCEL_SETTLE_S = 30.0


def _broker_end_proof(
    ctx: Any, run_dir: Path, broker_run: dict[str, Any], broker_status: dict[str, Any] | None
) -> str | None:
    """Why this non-terminal broker run has certainly ended, or None when that is not proven."""
    request_id = str(broker_run.get("request_id") or "")
    if broker_status is None:
        age = ctx.cancel_request_age_s(run_dir, request_id) if request_id else None
        return "cancelled_before_start" if age is not None and age >= _CANCEL_SETTLE_S else None
    if broker_status.get("state") == "terminal" or not ctx.heartbeat_is_past(broker_status.get("updated_utc")):
        return None
    # OLGA runs in the broker's kill-on-close job: once the broker is gone, so is OLGA.
    alive = ctx.broker_process_alive(broker_status.get("broker_pid"), broker_status.get("started_utc"))
    return "broker_gone" if alive is False else None


def _close_ended_broker_run(ctx: Any, run_dir: Path, ended: str) -> dict[str, Any]:
    with ctx._RECEIPT_RECOVERY_LOCK:
        current = ctx.load_run_record(run_dir)
        if current["phase"] == "terminal":
            return ctx._status_from_receipt_base(current, run_dir, str(current["state"]))
        staged_case_name = str(current.get("staged_case_name") or ctx.FIXED_CASE_NAME)
        started_wall_ns = int(current["broker_run"].get("started_wall_ns") or 0)
        try:
            native_completion = ctx.qualify_native_completion(run_dir, staged_case_name, started_wall_ns)
            outputs = ctx.collect_outputs(
                run_dir, companions=current.get("companions"), started_wall_ns=started_wall_ns
            )
        except (PermissionError, OSError):
            return ctx._status_from_receipt_base(current, run_dir, "finalizing")
        if ended == "cancelled_before_start":
            state, failure, cancelled = "cancelled", None, True
        else:
            completed = bool(native_completion["ok"])
            state = "completed" if completed else "failed"
            failure = None if completed else dict(_BROKER_GONE_FAILURE)
            cancelled = False
        current.update(
            {
                "phase": "terminal",
                "state": state,
                "failure": failure,
                "cancelled": cancelled,
                "outputs": outputs,
                "ok": state == "completed" and bool(current.get("validation_valid")),
                "engine_failed": state == "failed",
                "native_completion": native_completion,
                "solver_progress": ctx._solver_progress_for(
                    run_dir, staged_case_name, phase="terminal", liveness="terminal"
                ),
            }
        )
        if current["timestamps"].get("finished_at") is None:
            current["timestamps"]["finished_at"] = ctx._utc_now()
        try:
            ctx.write_run_record(run_dir, current)
        except (OSError, ctx.RunRecordError):
            return ctx._status_from_receipt_base(current, run_dir, "finalizing")
        return ctx._status_from_receipt_base(current, run_dir, state)


def status_from_receipt(ctx: Any, record: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    native_run = record.get("native_run")
    if (
        record["phase"] != "terminal"
        and isinstance(native_run, dict)
        and native_run.get("supervisor_boot") != ctx._SELECTION_BOOT_NONCE
    ):
        return _close_orphaned_native_run(ctx, record, run_dir)
    if record["phase"] != "terminal" and isinstance(record.get("broker_run"), dict):
        broker_run = record["broker_run"]
        request_id = str(broker_run.get("request_id") or "")
        try:
            broker_status = ctx.read_broker_status(run_dir, request_id) if request_id else None
        except ValueError as exc:
            broker_status = None
            broker_problem = str(exc)
        else:
            broker_problem = None
        if broker_status is not None and broker_status["state"] == "terminal":
            with ctx._RECEIPT_RECOVERY_LOCK:
                current = ctx.load_run_record(run_dir)
                if current["phase"] == "terminal":
                    return ctx._status_from_receipt_base(
                        current,
                        run_dir,
                        str(current["state"]),
                    )
                record = current
                broker_run = record["broker_run"]
                exit_code = int(broker_status["child_exit_code"])
                reason = str(broker_status.get("reason") or "")
                timed_out = reason == "timed_out"
                cancelled = reason in {"cancelled", "pre_cancelled"}
                log_tail = ctx.read_log_tail(run_dir, run_dir / "run.log", ctx.LOG_TAIL_CHARS)
                staged_case_name = str(
                    record.get("staged_case_name") or ctx.FIXED_CASE_NAME
                )
                started_wall_ns = int(broker_run.get("started_wall_ns") or 0)
                try:
                    native_completion = ctx.qualify_native_completion(
                        run_dir,
                        staged_case_name,
                        started_wall_ns,
                    )
                    outputs = ctx.collect_outputs(
                        run_dir,
                        companions=record.get("companions"),
                        started_wall_ns=started_wall_ns,
                    )
                except (PermissionError, OSError):
                    status = ctx._status_from_receipt_base(record, run_dir, "finalizing")
                    status.update(
                        {
                            "exit_code": exit_code,
                            "broker_status": broker_status,
                            "cancelled": cancelled,
                            "timed_out": timed_out,
                            "cancel_requested": False,
                            "collection_pending": True,
                            "recovery": (
                                "Native terminal output collection is pending; polling will retry."
                            ),
                        }
                    )
                    return status
                engine_failed = (
                    ctx._log_indicates_failure(log_tail) or not native_completion["ok"]
                )
                if cancelled:
                    recovered_state = "cancelled"
                elif timed_out:
                    recovered_state = "timed_out"
                elif exit_code == 0 and not engine_failed:
                    recovered_state = "completed"
                else:
                    recovered_state = "failed"
                ok = (
                    exit_code == 0
                    and not timed_out
                    and not cancelled
                    and bool(record.get("validation_valid"))
                    and not engine_failed
                )
                failure = ctx.diagnose_run_failure(
                    exit_code=exit_code,
                    engine_failed=engine_failed,
                    log_tail=log_tail,
                    command=record["command"],
                    output_count=len(outputs),
                    cancelled=cancelled,
                    timed_out=timed_out,
                    helper_problem=(
                        reason.removeprefix("broker_error:") or None
                        if reason.startswith("broker_error:")
                        else None
                    ),
                )
                prior_record = ctx.copy.deepcopy(record)
                record.update(
                    {
                        "phase": "terminal",
                        "state": recovered_state,
                        "exit_code": exit_code,
                        "failure": failure,
                        "outputs": outputs,
                        "timed_out": timed_out,
                        "cancelled": cancelled,
                        "ok": ok,
                        "engine_failed": engine_failed,
                        "log_tail": log_tail,
                        "broker_status": broker_status,
                        "native_completion": native_completion,
                        "solver_progress": ctx._solver_progress_for(
                            run_dir,
                            staged_case_name,
                            phase="terminal",
                            liveness="terminal",
                        ),
                    }
                )
                if record["timestamps"].get("finished_at") is None:
                    record["timestamps"]["finished_at"] = ctx._utc_now()
                try:
                    ctx.write_run_record(run_dir, record)
                except (OSError, ctx.RunRecordError):
                    persisted = ctx._reload_run_record_or(run_dir, prior_record)
                    if persisted.get("phase") == "terminal":
                        return ctx._status_from_receipt_base(
                            persisted,
                            run_dir,
                            str(persisted["state"]),
                        )
                    status = ctx._status_from_receipt_base(
                        persisted,
                        run_dir,
                        "finalizing",
                    )
                    status.update(
                        {
                            "exit_code": exit_code,
                            "broker_status": broker_status,
                            "native_completion": native_completion,
                            "cancelled": cancelled,
                            "timed_out": timed_out,
                            "cancel_requested": False,
                            "engine_failed": engine_failed,
                            "outputs": outputs,
                            "collection_pending": True,
                            "recovery": (
                                "Terminal receipt persistence is pending; polling will retry."
                            ),
                        }
                    )
                    return status
        elif broker_status is not None:
            updated_value = broker_status.get("updated_utc")
            if ctx.broker_heartbeat_is_live(updated_value):
                status = ctx._status_from_receipt_base(record, run_dir, "running")
                status["broker_status"] = broker_status
                status["recovery"] = (
                    "Recovered a recent broker heartbeat; native supervision is still running."
                )
                return status
            broker_problem = "The broker heartbeat is stale."
        ended = _broker_end_proof(ctx, run_dir, record["broker_run"], broker_status)
        if ended is not None and record["phase"] != "terminal":
            return _close_ended_broker_run(ctx, run_dir, ended)
        if record["phase"] != "terminal":
            status = ctx._status_from_receipt_base(record, run_dir, "supervision_unknown")
            status["broker_status"] = broker_status
            status["recovery"] = (
                "Run supervision was interrupted; broker terminal status is missing or unavailable."
                + (" " + broker_problem if broker_problem else "")
            )
            return status

    terminal = record["phase"] == "terminal"
    state = str(record["state"]) if terminal else "recovery_unknown"
    status = ctx._status_from_receipt_base(record, run_dir, state)
    status["recovery"] = (
        None
        if terminal
        else "The persisted run was not terminal and no live process is registered; completion is unknown."
    )
    return status
