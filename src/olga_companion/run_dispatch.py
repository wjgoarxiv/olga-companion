from __future__ import annotations

import logging
from pathlib import PureWindowsPath, Path
from typing import Any

from .run_model import PreparedRun
from .runtime_logging import LOGGER_NAME


def _missing_file_name(exc: BaseException) -> str | None:
    """Only the file's name, never its folder, so the log holds no private path."""
    filename = getattr(exc, "filename", None)
    if not filename:
        return None
    return PureWindowsPath(str(filename)).name or None


def dispatch_prepared(ctx: Any, prepared: PreparedRun) -> dict[str, Any]:
    run_id = prepared.run_id
    run_dir = prepared.run_dir
    detection = prepared.detection
    receipt = prepared.receipt
    log_path = run_dir / "run.log"
    prepared_broker = None
    started_wall_ns = ctx.time.time_ns()
    if prepared.contained_runtime is not None:
        try:
            runtime_unchanged = ctx._contained_runtime_matches(
                prepared.contained_runtime,
                str(detection["sha256"]),
            )
        except OSError:
            runtime_unchanged = False
        if not runtime_unchanged:
            ctx.shutil.rmtree(run_dir, ignore_errors=True)
            raise ctx.OlgaInputError(
                "Contained OLGA runtime artifact changed during preflight; run was not launched."
            )
    try:
        if prepared.artifact is not None:
            prepared_broker = ctx.prepare_broker_run(
                run_dir=run_dir,
                artifact=prepared.artifact,
                engine=Path(str(detection["exe"])),
                engine_sha256=str(detection["sha256"]),
                staged_case=prepared.working_copy,
                staged_case_sha256=prepared.staged_source_hash,
                timeout_s=prepared.timeout_s,
            )
            receipt["broker_run"] = {
                "request_id": prepared_broker.request_id,
                "protocol": prepared.artifact.protocol,
                "broker_sha256": prepared.artifact.sha256,
                "status_name": prepared_broker.status_path.name,
                "cancel_name": prepared_broker.cancel_path.name,
                "started_wall_ns": started_wall_ns,
            }
            receipt["dispatcher_command"] = prepared_broker.dispatch_command
            ctx.write_run_record(run_dir, receipt)
            dispatcher = ctx.subprocess.Popen(
                prepared_broker.dispatch_command,
                cwd=str(run_dir),
                stdout=ctx.subprocess.DEVNULL,
                stderr=ctx.subprocess.DEVNULL,
            )
            popen = ctx.BrokerProcess(dispatcher, run_dir, prepared_broker.request_id)
        elif prepared.launch_strategy == "native_job":
            engine = Path(str(detection["exe"]))
            if ctx.file_sha256(engine) != str(detection["sha256"]):
                raise ValueError("The OLGA engine changed after approval; it was not started.")
            # The engine dies with this sidecar process (kill-on-close job), so a later
            # sidecar may close a record this one left open.
            receipt["native_run"] = {
                "supervisor_boot": ctx._SELECTION_BOOT_NONCE,
                "started_wall_ns": started_wall_ns,
            }
            with log_path.open("wb") as log_handle:
                popen = ctx.launch_in_job(prepared.command, cwd=run_dir, stdout=log_handle)
            receipt["native_run"]["in_job"] = bool(getattr(popen, "in_job", True))
        else:
            with log_path.open("wb") as log_handle:
                popen = ctx.subprocess.Popen(
                    prepared.command,
                    cwd=str(run_dir),
                    stdout=log_handle,
                    stderr=ctx.subprocess.STDOUT,
                    start_new_session=ctx.os.name == "posix",
                )
    except (OSError, ValueError) as exc:
        receipt.update(
            {
                "phase": "terminal",
                "state": "failed",
                "solver_progress": ctx._solver_progress_for(
                    run_dir,
                    prepared.staged_case_name,
                    phase="terminal",
                    liveness="terminal",
                ),
                "failure": {
                    "code": "process_start_failed",
                    "title": "OLGA process did not start",
                    "detail": str(exc),
                    "action": (
                        "Verify the selected runtime is available, then request a fresh preview."
                    ),
                    "auto_retry_safe": False,
                },
            }
        )
        receipt["timestamps"]["finished_at"] = ctx._utc_now()
        ctx.write_run_record(run_dir, receipt)
        missing = _missing_file_name(exc)
        logging.getLogger(LOGGER_NAME).warning(
            "run_start_failed strategy=%s kind=%s errno=%s file=%s",
            prepared.launch_strategy,
            type(exc).__name__,
            getattr(exc, "errno", None),
            missing or "-",
        )
        # Nothing was started, so this is a refusal the person can act on, not a 500.
        not_found = isinstance(exc, FileNotFoundError)
        if missing:
            reason = (
                f"a required file was not found: {missing}"
                if not_found
                else f"{type(exc).__name__} for {missing}"
            )
        else:
            reason = type(exc).__name__
        hint = (
            " Security software may have removed or blocked the app's run helper; ask IT to "
            "allow it, then request a fresh preview."
            if missing and missing.casefold().endswith("broker.exe")
            else " Check the selected OLGA runtime, then request a fresh preview."
        )
        raise ctx.OlgaInputError(f"OLGA did not start ({reason}).{hint}") from exc

    timer = ctx.threading.Timer(prepared.timeout_s, ctx._on_timeout, args=[run_id])
    timer.daemon = True
    validation_valid = (
        prepared.validation["valid"]
        and not prepared.companions["pvt_missing"]
        and not prepared.companions["restart_missing"]
    )
    state = ctx._RunState(
        popen=popen,
        run_dir=run_dir,
        log_path=log_path,
        command=prepared.command,
        detection=detection,
        selection_id=prepared.selection_id,
        validation_valid=validation_valid,
        timeout_s=prepared.timeout_s,
        started_monotonic=ctx.time.monotonic(),
        timer=timer,
        receipt=receipt,
        launch_strategy=prepared.launch_strategy,
        broker=None if prepared_broker is None else receipt.get("broker_run"),
        staged_case_name=prepared.staged_case_name,
        started_wall_ns=started_wall_ns,
    )
    with ctx._REGISTRY_LOCK:
        ctx._RUNS[run_id] = state
    receipt["phase"] = "running"
    receipt["state"] = "running"
    receipt["timestamps"]["started_at"] = ctx._utc_now()
    try:
        ctx.write_run_record(run_dir, receipt)
    except (OSError, ctx.RunRecordError):
        with state.lock:
            state.cancelled = True
            ctx._kill(state)
        with ctx._REGISTRY_LOCK:
            ctx._RUNS.pop(run_id, None)
        raise
    if prepared.artifact is None:
        timer.start()

    reaper = ctx.threading.Thread(target=ctx._reap, args=[run_id, state], daemon=True)
    reaper.start()
    return {
        "run_id": run_id,
        "state": "running",
        "run_dir": str(run_dir),
        "command": prepared.command,
        "approved_command": prepared.approved_command,
        "detection": detection,
        "selection_id": prepared.selection_id,
        "candidate_id": detection.get("candidate_id"),
        "runtime_id": detection.get("runtime_id"),
        "validation": prepared.validation,
        "approved": prepared.approved,
        "override": prepared.override,
        "timeout_s": prepared.timeout_s,
        "source": str(prepared.source),
        "source_sha256": prepared.source_hash,
        "launch_strategy": prepared.launch_strategy,
        "broker": receipt.get("broker_run"),
        "staged_case_name": prepared.staged_case_name,
        **(
            {"execution_artifact": prepared.execution_artifact}
            if prepared.execution_artifact is not None
            else {}
        ),
        **prepared.companions,
    }
