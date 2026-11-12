from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from olga_companion.run_patrol import PatrolDependencies, PatrolInputError, patrol_run


@dataclass(slots=True)
class FakePatrol:
    statuses: list[dict[str, Any]]
    monitor: dict[str, Any]
    diagnosis: dict[str, Any] = field(default_factory=dict)
    now: float = 0.0
    status_calls: int = 0
    monitor_calls: int = 0
    diagnose_calls: int = 0

    def status(self, _run_id: str) -> dict[str, Any]:
        index = min(self.status_calls, len(self.statuses) - 1)
        self.status_calls += 1
        return self.statuses[index]

    def snapshot(self, _out: str, _log: str | None = None) -> dict[str, Any]:
        self.monitor_calls += 1
        return self.monitor

    def diagnose(self, _out: str) -> dict[str, Any]:
        self.diagnose_calls += 1
        return self.diagnosis

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def dependencies(self) -> PatrolDependencies:
        return PatrolDependencies(
            run_status=self.status,
            monitor_snapshot=self.snapshot,
            diagnose_out=self.diagnose,
            monotonic=self.monotonic,
            sleep=self.sleep,
        )


def _running(*, recovered: bool = False) -> dict[str, Any]:
    return {
        "state": "running",
        "elapsed_ms": 1200,
        "recovered_from_receipt": recovered,
        "run_dir": "/private/runs/run-1",
        "solver_progress": {
            "phase": "running",
            "liveness": "supervised",
            "files": {"out": "case.out", "run_log": "run.log"},
        },
    }


def test_patrol_reports_only_observed_vendor_progress_then_clean_terminal() -> None:
    # Given a live observation followed by a recovered clean receipt.
    fake = FakePatrol(
        statuses=[_running(), {"state": "completed", "ok": True, "recovered_from_receipt": True}],
        monitor={
            "parse_status": "parsed",
            "activity_status": "active",
            "simulation_time_s": 12.0,
            "step": 20,
            "adaptive_total_steps": 9000,
            "vendor_percent": 25.0,
            "fraction": 0.25,
            "phase": "running",
            "liveness": "supervised",
        },
    )

    # When patrol reaches the durable terminal receipt.
    result = patrol_run("run-1", deadline_s=5, max_polls=3, backoff_s=1, dependencies=fake.dependencies())

    # Then observed progress is preserved and no anomaly is invented.
    assert result["state"] == "completed"
    assert result["terminal"] is True
    assert result["recovered_from_receipt"] is True
    assert result["observations"][0]["vendor_percent"] == 25.0
    assert result["observations"][0]["fraction"] == 0.25
    assert result["anomaly"] is None
    assert result["diagnosis"] is None
    assert result["proposal"] is None
    assert result["actions_dispatched"] == []


def test_adaptive_step_denominator_never_becomes_a_fake_percentage() -> None:
    # Given adaptive step evidence without an explicit vendor percentage.
    fake = FakePatrol(
        statuses=[_running()],
        monitor={"parse_status": "parsed", "step": 5000, "adaptive_total_steps": 5100},
    )

    # When one bounded observation is taken.
    result = patrol_run("run-1", deadline_s=5, max_polls=1, backoff_s=1, dependencies=fake.dependencies())

    # Then the adaptive denominator remains raw evidence, not progress.
    observation = result["observations"][0]
    assert observation["step"] == 5000
    assert observation["adaptive_total_steps"] == 5100
    assert "vendor_percent" not in observation
    assert "fraction" not in observation


@pytest.mark.parametrize("parse_status", ["stale", "malformed", "missing"])
def test_nonterminal_unusable_logs_remain_inert_evidence(parse_status: str) -> None:
    # Given a running process with unusable solver evidence.
    fake = FakePatrol(statuses=[_running()], monitor={"parse_status": parse_status})

    # When patrol exhausts its bounded poll allowance.
    result = patrol_run("run-1", deadline_s=5, max_polls=1, backoff_s=1, dependencies=fake.dependencies())

    # Then process truth wins and no solver anomaly is fabricated.
    assert result["state"] == "running"
    assert result["stop_reason"] == "poll_limit"
    assert result["anomaly"] is None
    assert result["diagnosis"] is None


def test_hung_running_patrol_stops_uncertain_at_deadline() -> None:
    # Given a run that never leaves the running state.
    fake = FakePatrol(statuses=[_running()], monitor={"parse_status": "missing"})

    # When the deterministic patrol deadline is reached.
    result = patrol_run("run-1", deadline_s=2, max_polls=10, backoff_s=1, dependencies=fake.dependencies())

    # Then it stops uncertain rather than claiming terminal timeout or success.
    assert result["state"] == "uncertain"
    assert result["terminal"] is False
    assert result["stop_reason"] == "deadline"
    assert result["polls"] == 2


@pytest.mark.parametrize(("deadline", "backoff"), [(float("nan"), 1.0), (5.0, float("inf"))])
def test_nonfinite_bounds_are_rejected(deadline: float, backoff: float) -> None:
    # Given a non-finite patrol bound.
    fake = FakePatrol(statuses=[_running()], monitor={})

    # When the request crosses the patrol boundary, then it fails before polling.
    with pytest.raises(PatrolInputError):
        patrol_run(
            "run-1", deadline_s=deadline, max_polls=2, backoff_s=backoff, dependencies=fake.dependencies()
        )
    assert fake.status_calls == 0


@pytest.mark.parametrize(
    ("status", "expected_state", "terminal", "reason"),
    [
        ({"state": "cancelled", "cancelled": True}, "cancelled", True, "terminal"),
        ({"state": "timed_out", "timed_out": True}, "timed_out", True, "terminal"),
        ({"state": "supervision_unknown"}, "uncertain", False, "supervision_unknown"),
        ({"state": "recovery_unknown"}, "uncertain", False, "recovery_unknown"),
        ({"state": "receipt_error"}, "uncertain", False, "receipt_error"),
    ],
)
def test_cancel_timeout_and_unknown_states_are_truthful(
    status: dict[str, Any], expected_state: str, terminal: bool, reason: str
) -> None:
    # Given one persisted lifecycle state.
    fake = FakePatrol(statuses=[status], monitor={})

    # When patrol observes it.
    result = patrol_run("run-1", deadline_s=5, max_polls=3, backoff_s=1, dependencies=fake.dependencies())

    # Then the returned lifecycle truth is explicit and diagnosis is not attempted.
    assert result["state"] == expected_state
    assert result["terminal"] is terminal
    assert result["stop_reason"] == reason
    assert fake.diagnose_calls == 0
