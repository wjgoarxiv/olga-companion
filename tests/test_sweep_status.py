from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from olga_companion import runner, sweep_execution, sweep_monitor, sweep_status
from sweep_test_support import _synthetic_sweep


def _child_status(
    state: str, *, ok: bool = False, cancel_requested: bool = False
) -> dict[str, Any]:
    return {
        "state": state,
        "ok": ok,
        "exit_code": 0 if ok else None,
        "engine_failed": False,
        "elapsed_ms": 1000,
        "log_tail": "",
        "cancel_requested": cancel_requested,
        "solver_progress": runner._indeterminate_solver_progress(),
    }


@pytest.mark.parametrize("child_state", ["finalizing", "supervision_unknown"])
def test_nonterminal_supervision_states_keep_elapsed_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, child_state: str
) -> None:
    state = _synthetic_sweep(tmp_path)
    reported_state = [child_state]
    monkeypatch.setattr(
        sweep_execution.runner,
        "run_status",
        lambda run_id: _child_status(
            reported_state[0], ok=reported_state[0] == "completed"
        ),
    )
    clock = iter([20.0, 22.0, 24.0, 26.0])
    monkeypatch.setattr(sweep_status.time, "monotonic", lambda: next(clock))

    first = sweep_execution._status_for_state(state)
    second = sweep_execution._status_for_state(state)

    assert first["state"] == child_state
    assert first["elapsed_ms"] == 10_000
    assert second["elapsed_ms"] == 12_000
    assert state.finished_monotonic is None

    reported_state[0] = "completed"
    terminal = sweep_execution._status_for_state(state)
    later = sweep_execution._status_for_state(state)

    assert terminal["elapsed_ms"] == 14_000
    assert later["elapsed_ms"] == terminal["elapsed_ms"]
    assert state.finished_monotonic == 24.0


def test_timed_out_child_aggregates_to_timed_out_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _synthetic_sweep(tmp_path)
    monkeypatch.setattr(
        sweep_execution.runner,
        "run_status",
        lambda run_id: _child_status("timed_out"),
    )

    result = sweep_execution._status_for_state(state)

    assert result["state"] == "timed_out"
    assert result["counts"]["timed_out"] == 1
    assert result["ok"] is False
    assert state.finished_monotonic is not None
    completed = {"state": "completed"}
    timed_out = {"state": "timed_out"}
    assert (
        sweep_execution._aggregate_state([completed, timed_out], True, False)
        == "timed_out"
    )
    for active in ("running", "finalizing", "supervision_unknown"):
        assert (
            sweep_execution._aggregate_state(
                [{"state": active}, timed_out], True, False
            )
            == active
        )
    assert sweep_execution._aggregate_state([timed_out], True, True) == "cancelled"


def test_cancelling_planned_sweep_preserves_unstarted_case_truth(
    tmp_path: Path,
) -> None:
    state = _synthetic_sweep(tmp_path, run_id=None, started=False)

    sweep_monitor.cancel_state(state)
    result = sweep_execution._status_for_state(state)

    assert result["state"] == "cancelled"
    assert result["cases"][0]["state"] == "planned"
    assert result["ok"] is False


def test_cancelling_completed_sweep_is_a_truthful_no_op(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _synthetic_sweep(tmp_path)
    cancelled_ids: list[str] = []
    monkeypatch.setattr(
        sweep_execution.runner,
        "run_status",
        lambda run_id: _child_status("completed", ok=True, cancel_requested=True),
    )
    monkeypatch.setattr(
        sweep_execution.runner,
        "cancel_run",
        lambda run_id: cancelled_ids.append(run_id),
    )

    sweep_monitor.cancel_state(state)
    result = sweep_execution._status_for_state(state)

    assert cancelled_ids == []
    assert state.cancelled is False
    assert result["state"] == "completed"
    assert result["ok"] is True


def test_completed_status_remains_truthful_when_cancel_and_status_overlap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _synthetic_sweep(tmp_path)
    monkeypatch.setattr(
        sweep_execution.runner,
        "run_status",
        lambda run_id: _child_status("completed", ok=True),
    )
    monkeypatch.setattr(sweep_execution.runner, "cancel_run", lambda run_id: None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel_future = pool.submit(sweep_monitor.cancel_state, state)
        status_future = pool.submit(sweep_execution._status_for_state, state)
        cancel_future.result(timeout=5)
        status_future.result(timeout=5)

    final = sweep_execution._status_for_state(state)
    assert state.cancelled is False
    assert final["state"] == "completed"
    assert final["ok"] is True
