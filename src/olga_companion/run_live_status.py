from __future__ import annotations

from typing import Any


def live_run_status(ctx: Any, run_id: str, state: Any) -> dict[str, Any]:
    exit_code = state.popen.poll()
    is_broker = isinstance(state.popen, ctx.BrokerProcess)
    broker_status = state.popen.status() if is_broker else None
    supervision_error = state.popen.supervision_error if is_broker else None
    if broker_status is not None:
        reason = broker_status.get("reason")
        if broker_status.get("state") == "terminal":
            state.timed_out = reason == "timed_out"
            state.cancelled = reason in {"cancelled", "pre_cancelled"}
    if exit_code is not None:
        with state.lock:
            if state.finished_monotonic is None:
                state.finished_monotonic = ctx.time.monotonic()
    log_tail = ctx.read_log_tail(state.run_dir, state.log_path, ctx.LOG_TAIL_CHARS)
    engine_failed = ctx._log_indicates_failure(log_tail)
    native_completion: dict[str, Any] | None = None
    collection_error = False
    if exit_code is not None and state.launch_strategy == "explorer_one_shot_broker":
        try:
            native_completion = ctx.qualify_native_completion(
                state.run_dir,
                state.staged_case_name,
                state.started_wall_ns,
            )
        except (PermissionError, OSError):
            collection_error = True
        else:
            engine_failed = (
                engine_failed or not native_completion["ok"] or supervision_error is not None
            )
    if exit_code is None:
        run_state = "running"
    else:
        state.timer.cancel()
        if state.cancelled:
            run_state = "cancelled"
        elif state.timed_out:
            run_state = "timed_out"
        elif exit_code == 0 and not engine_failed:
            run_state = "completed"
        else:
            run_state = "failed"
    ok = (
        exit_code == 0
        and not state.timed_out
        and not state.cancelled
        and state.validation_valid
        and not engine_failed
    )
    outputs: list[dict[str, Any]] = []
    if exit_code is not None and not collection_error:
        try:
            outputs = ctx.collect_outputs(
                state.run_dir,
                companions=state.receipt.get("companions"),
                started_wall_ns=state.started_wall_ns,
            )
        except (PermissionError, OSError):
            collection_error = True
    if collection_error:
        run_state = "finalizing"
        ok = False
        failure = None
    else:
        failure = ctx.diagnose_run_failure(
            exit_code=exit_code,
            engine_failed=engine_failed,
            log_tail=log_tail,
            command=state.command,
            output_count=len(outputs),
            cancelled=state.cancelled,
            timed_out=state.timed_out,
        )
    solver_progress = ctx._solver_progress_for(
        state.run_dir,
        state.staged_case_name,
        phase=(
            "running"
            if exit_code is None
            else "finalizing"
            if collection_error
            else "terminal"
        ),
        liveness="supervised" if exit_code is None else "terminal",
    )
    status = {
        "run_id": run_id,
        "state": run_state,
        "exit_code": exit_code,
        "timed_out": state.timed_out,
        "cancelled": state.cancelled,
        "cancel_requested": bool(state.cancelled and exit_code is None),
        "ok": ok,
        "engine_failed": engine_failed,
        "validation_valid": state.validation_valid,
        "log_tail": ctx.redact_log_paths(log_tail),
        "run_dir": str(state.run_dir),
        "command": state.command,
        "detection": state.detection,
        "selection_id": state.selection_id,
        "outputs": outputs,
        "failure": failure,
        "elapsed_ms": int(
            ((state.finished_monotonic or ctx.time.monotonic()) - state.started_monotonic)
            * 1000
        ),
        "launch_strategy": state.launch_strategy,
        "broker_status": broker_status,
        "supervision_error": supervision_error,
        "native_completion": native_completion,
        "solver_progress": solver_progress,
        "collection_pending": collection_error,
    }
    if exit_code is not None and not collection_error:
        with state.lock:
            if state.receipt.get("phase") == "terminal" and isinstance(
                state.receipt.get("solver_progress"),
                dict,
            ):
                status["solver_progress"] = ctx.copy.deepcopy(state.receipt["solver_progress"])
            else:
                receipt = ctx.copy.deepcopy(state.receipt)
                receipt.update(
                    {
                        "phase": "terminal",
                        "state": run_state,
                        "exit_code": exit_code,
                        "failure": failure,
                        "outputs": outputs,
                        "timed_out": state.timed_out,
                        "cancelled": state.cancelled,
                        "ok": ok,
                        "engine_failed": engine_failed,
                        "validation_valid": state.validation_valid,
                        "elapsed_ms": status["elapsed_ms"],
                        "log_tail": log_tail,
                        "broker_status": broker_status,
                        "supervision_error": supervision_error,
                        "native_completion": native_completion,
                        "solver_progress": solver_progress,
                    }
                )
                if receipt["timestamps"].get("finished_at") is None:
                    receipt["timestamps"]["finished_at"] = ctx._utc_now()
                try:
                    ctx.write_run_record(state.run_dir, receipt)
                except (OSError, ctx.RunRecordError):
                    persisted = ctx._reload_run_record_or(state.run_dir, state.receipt)
                    if persisted.get("phase") == "terminal":
                        state.receipt = persisted
                    else:
                        state.receipt = persisted
                        status.update(
                            {
                                "state": "finalizing",
                                "ok": False,
                                "failure": None,
                                "collection_pending": True,
                                "recovery": (
                                    "Terminal receipt persistence is pending; polling will retry."
                                ),
                            }
                        )
                else:
                    state.receipt = receipt
    from .run_solver_findings import attach_solver_findings

    attach_solver_findings(status)
    return status


def reload_run_record_or(ctx: Any, run_dir: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return ctx.load_run_record(run_dir)
    except (FileNotFoundError, OSError, ctx.RunRecordError):
        return ctx.copy.deepcopy(fallback)
