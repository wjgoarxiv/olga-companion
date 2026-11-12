from __future__ import annotations

from typing import Any


def execute_run(
    ctx: Any,
    source_value: str,
    *,
    approved: bool,
    override: bool,
    timeout_s: int,
    selection_id: str | None,
    pinned_detection: dict[str, Any] | None,
    candidate_id: str | None,
) -> dict[str, Any]:
    claimed_selection_id = selection_id if approved and selection_id else None
    with ctx._REGISTRY_LOCK:
        expected_identity = (
            ctx._SELECTION_CONTEXTS.get(claimed_selection_id)
            if claimed_selection_id is not None
            else None
        )
        if claimed_selection_id is not None:
            duplicate = claimed_selection_id in ctx._PREPARING_SELECTION_IDS or any(
                state.selection_id == claimed_selection_id and state.popen.poll() is None
                for state in ctx._RUNS.values()
            )
            if duplicate:
                raise ctx.OlgaInputError(
                    "This approved selection is already preparing or running. "
                    "Monitor/cancel the existing run before launching it again."
                )
            ctx._PREPARING_SELECTION_IDS.add(claimed_selection_id)
    try:
        if expected_identity is None:
            expected_identity = ctx.workspace.context_identity()
        expected_root, expected_generation = expected_identity
        with ctx.workspace.expected_context(expected_generation) as current_identity:
            if current_identity[0] != expected_root:
                raise ctx.workspace.StaleWorkspaceContextError(
                    "Workspace context changed; refresh the preview and approve again."
                )
            return ctx._execute_run_claimed(
                source_value,
                approved=approved,
                override=override,
                timeout_s=timeout_s,
                selection_id=selection_id,
                pinned_detection=pinned_detection,
                candidate_id=candidate_id,
            )
    finally:
        if claimed_selection_id is not None:
            with ctx._REGISTRY_LOCK:
                ctx._PREPARING_SELECTION_IDS.discard(claimed_selection_id)


def get_state(ctx: Any, run_id: str) -> Any:
    with ctx._REGISTRY_LOCK:
        state = ctx._RUNS.get(run_id)
    if state is None:
        raise ctx.UnknownRunError(run_id)
    return state


def kill(ctx: Any, state: Any) -> None:
    process_group_id = (
        state.popen.pid
        if ctx.os.name == "posix" and not isinstance(state.popen, ctx.BrokerProcess)
        else None
    )
    ctx.terminate_process(state.popen, process_group_id=process_group_id)


def shutdown_direct_runs(ctx: Any) -> None:
    with ctx._REGISTRY_LOCK:
        direct_runs = [
            (run_id, state)
            for run_id, state in ctx._RUNS.items()
            if not isinstance(state.popen, ctx.BrokerProcess)
        ]
        for run_id, _state in direct_runs:
            del ctx._RUNS[run_id]
    for _run_id, state in direct_runs:
        state.timer.cancel()
        with state.lock:
            if state.popen.poll() is None:
                state.cancelled = True
            ctx._kill(state)


def reap(ctx: Any, run_id: str, state: Any) -> None:
    state.popen.wait()
    with state.lock:
        if state.finished_monotonic is None:
            state.finished_monotonic = ctx.time.monotonic()
    state.timer.cancel()
    ctx._live_run_status(run_id, state)


def on_timeout(ctx: Any, run_id: str) -> None:
    try:
        state = ctx._get_state(run_id)
    except ctx.UnknownRunError:
        return
    with state.lock:
        if state.popen.poll() is None:
            state.timed_out = True
            ctx._kill(state)


def cancel_run(ctx: Any, run_id: str) -> dict[str, Any]:
    with ctx._REGISTRY_LOCK:
        state = ctx._RUNS.get(run_id)
    if state is not None:
        with state.lock:
            if state.popen.poll() is None:
                state.cancelled = True
                ctx._kill(state)
        try:
            state.popen.wait(timeout=10)
        except ctx.subprocess.TimeoutExpired:
            return ctx.run_status(run_id)
        return ctx.run_status(run_id)

    ctx.require_run_id(run_id)
    run_dir = ctx.sandbox_root() / "runs" / run_id
    try:
        record = ctx.load_run_record(run_dir)
    except FileNotFoundError as exc:
        raise ctx.UnknownRunError(run_id) from exc
    broker_run = record.get("broker_run")
    if (
        record["phase"] == "terminal"
        or not isinstance(broker_run, dict)
        or broker_run.get("protocol") != ctx.BROKER_PROTOCOL
        or not isinstance(broker_run.get("request_id"), str)
    ):
        return ctx._status_from_receipt(record, run_dir)

    ctx.request_broker_cancel(run_dir, str(broker_run["request_id"]), reason="cancelled")
    deadline = ctx.time.monotonic() + 10
    while True:
        status = ctx.run_status(run_id)
        if status["state"] in {"completed", "failed", "cancelled", "timed_out"}:
            return status
        if ctx.time.monotonic() >= deadline:
            status["cancel_requested"] = True
            status["recovery"] = (
                "Cancellation is persisted; broker terminal status is still pending."
            )
            return status
        ctx.time.sleep(0.05)
