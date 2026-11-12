from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .genkey_static import OlgaInputError
from .sweep_monitor import aggregate_state, case_status
from .sweep_selection import MAX_SWEEP_CASES, SweepState, approval_payload


TERMINAL_STATES = {"completed", "failed", "cancelled", "timed_out"}


def status_for_state(
    state: SweepState,
    case_status_factory: Callable[[Any, bool], dict[str, Any]] = case_status,
    aggregate_state_factory: Callable[
        [list[dict[str, Any]], bool, bool], str
    ] = aggregate_state,
    approval_payload_factory: Callable[[str, str], dict[str, str]] = approval_payload,
) -> dict[str, Any]:
    if len(state.cases) > MAX_SWEEP_CASES:
        raise OlgaInputError(
            f"Sweep registry exceeds the {MAX_SWEEP_CASES}-case status limit."
        )
    with state.lock:
        cases = [case_status_factory(case, state.cancelled) for case in state.cases]
        started = state.started_monotonic is not None
        aggregate = aggregate_state_factory(cases, started, state.cancelled)
        now = time.monotonic()
        if started:
            if aggregate in TERMINAL_STATES and state.finished_monotonic is None:
                state.finished_monotonic = now
            elif aggregate not in TERMINAL_STATES:
                state.finished_monotonic = None
        elapsed_ms = int(
            (
                (state.finished_monotonic or now)
                - (state.started_monotonic or state.created_monotonic)
            )
            * 1000
        )
    ok = (
        aggregate == "planned" and all(bool(case.get("valid")) for case in cases)
        if not started
        else (aggregate == "completed" and all(bool(case.get("ok")) for case in cases))
    )
    return {
        "sweep_id": state.sweep_id,
        "state": aggregate,
        "ok": ok,
        "dry_run": not started,
        "base": str(state.base),
        "strategy": state.strategy,
        "sweeps": state.sweeps,
        "timeout_s": state.timeout_s,
        "output_dir": state.output_dir,
        "command": state.command,
        "detection": state.detection,
        "plan_id": state.plan_id,
        "context_generation": state.context_generation,
        "cases": cases,
        "plan": cases,
        "case_count": len(cases),
        "counts": {
            name: sum(1 for case in cases if case["state"] == name)
            for name in (
                "planned",
                "running",
                "finalizing",
                "supervision_unknown",
                "completed",
                "failed",
                "cancelled",
                "timed_out",
            )
        },
        "elapsed_ms": elapsed_ms,
        "approval_payload": approval_payload_factory(state.sweep_id, state.plan_id),
    }
