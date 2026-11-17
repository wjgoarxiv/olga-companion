from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from olga_companion import diagnostics, runner
from olga_companion.run_records import load_run_record, write_run_record


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "progress"


def _live_state(
    run_dir: Path,
    *,
    poll_result: int | None,
    receipt: dict[str, Any] | None = None,
) -> runner._RunState:
    popen = SimpleNamespace(poll=lambda: poll_result)
    if poll_result is not None:
        popen.wait = lambda timeout=None: poll_result
    return runner._RunState(
        popen=popen,
        run_dir=run_dir,
        log_path=run_dir / "run.log",
        command=["fake", "owner.genkey"],
        detection={},
        selection_id="selection",
        validation_valid=True,
        timeout_s=30,
        started_monotonic=time.monotonic() - 2,
        timer=Mock(),
        receipt=receipt or {"phase": "running", "timestamps": {"finished_at": None}},
        staged_case_name="owner.genkey",
    )


def _receipt(
    run_id: str,
    *,
    phase: str = "running",
    state: str = "running",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "phase": phase,
        "state": state,
        "source": {"name": "owner.genkey", "sha256": "a", "staged_sha256": "a"},
        "runtime": {
            "candidate_id": "c",
            "runtime_id": "r",
            "version": "v",
            "kind": "script",
            "exe": "fake",
        },
        "companions": [],
        "selection_id": "selection",
        "validation": {},
        "validation_valid": True,
        "timestamps": {
            "prepared_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:01Z",
            "finished_at": "2026-01-01T00:00:02Z" if phase == "terminal" else None,
        },
        "command": ["fake", "owner.genkey"],
        "exit_code": 0 if phase == "terminal" else None,
        "failure": None,
        "outputs": [],
        "staged_case_name": "owner.genkey",
    }
def test_stale_supervised_output_and_vendor_100_percent_do_not_terminalize_live_process(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    out_path = run_dir / "owner.out"
    out_path.write_text(
        "--*++*-- Time: 900s. Step no: 4/9910. Current step-size: 0.25s\n",
        encoding="utf-8",
    )
    (run_dir / "run.log").write_text(
        "Elapsed simulation-time is now: 15 MIN ( 100.0% of simulation completed )\n",
        encoding="utf-8",
    )
    stale = time.time() - diagnostics._LIVENESS_STALE_SECONDS - 10
    os.utime(out_path, (stale, stale))
    os.utime(run_dir / "run.log", (stale, stale))

    status = runner._live_run_status("run-live", _live_state(run_dir, poll_result=None))

    assert status["state"] == "running"
    assert status["solver_progress"]["fraction"] == 1.0
    assert status["solver_progress"]["activity_status"] == "stale"
    assert status["solver_progress"]["phase"] == "running"
    assert status["solver_progress"]["liveness"] == "supervised"


def test_future_file_mtime_beyond_clock_skew_tolerance_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out_path = tmp_path / "future.out"
    out_path.write_text(
        "--*++*-- Time: 9s. Step no: 9/99. Current step-size: 0.5s\n",
        encoding="utf-8",
    )
    now = time.time()
    future = now + diagnostics._CLOCK_SKEW_TOLERANCE_SECONDS + 5
    os.utime(out_path, (future, future))
    monkeypatch.setattr(diagnostics.time, "time", lambda: now)

    snapshot = diagnostics.monitor_snapshot(str(out_path))

    assert snapshot["activity_status"] == "clock_skew"
    assert snapshot["liveness"] == "indeterminate"
    assert snapshot["activity_status"] != "active"


def test_runner_uses_only_exact_staged_case_stem_for_out_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "owner.out").write_text(
        "--*++*-- Time: 50s. Step no: 5/500. Current step-size: 0.5s\n",
        encoding="utf-8",
    )
    (run_dir / "other.out").write_text(
        "--*++*-- Time: 999s. Step no: 999/999. Current step-size: 9s\n",
        encoding="utf-8",
    )

    status = runner._live_run_status("exact-stem", _live_state(run_dir, poll_result=None))

    assert status["solver_progress"]["files"]["out"] == "owner.out"
    assert status["solver_progress"]["simulation_time_s"] == 50.0
    assert status["solver_progress"]["step"] == 5


def test_terminal_progress_is_persisted_and_restart_reads_it_without_rewriting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "runs" / "terminal-run"
    run_dir.mkdir(parents=True)
    (run_dir / "owner.out").write_bytes((FIXTURE_DIR / "demo_adaptive.out").read_bytes())
    (run_dir / "run.log").write_bytes((FIXTURE_DIR / "demo_run.log").read_bytes())
    receipt = _receipt("terminal-run")
    write_run_record(run_dir, receipt)
    state = _live_state(run_dir, poll_result=0, receipt=receipt)

    terminal = runner._live_run_status("terminal-run", state)
    persisted = load_run_record(run_dir)
    before = (run_dir / "run.json").read_bytes()
    with runner._REGISTRY_LOCK:
        runner._RUNS.pop("terminal-run", None)
    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path)
    restarted = runner.run_status("terminal-run")
    after = (run_dir / "run.json").read_bytes()

    assert terminal["solver_progress"]["phase"] == "terminal"
    assert persisted["solver_progress"] == terminal["solver_progress"]
    assert restarted["solver_progress"] == persisted["solver_progress"]
    assert after == before


def test_old_terminal_receipt_and_receipt_error_have_honest_indeterminate_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs = tmp_path / "runs"
    old_dir = runs / "old-terminal"
    old_dir.mkdir(parents=True)
    old = _receipt("old-terminal", phase="terminal", state="completed")
    write_run_record(old_dir, old)
    broken_dir = runs / "broken-receipt"
    broken_dir.mkdir()
    (broken_dir / "run.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path)

    old_status = runner.run_status("old-terminal")
    history = runner.recent_runs(limit=10)
    broken = next(item for item in history if item["state"] == "receipt_error")

    assert old_status["solver_progress"]["parse_status"] == "indeterminate"
    assert old_status["solver_progress"]["phase"] == "terminal"
    assert broken["solver_progress"]["parse_status"] == "indeterminate"


def test_pending_cancel_is_nonterminal_and_remains_pollable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = _live_state(run_dir, poll_result=None)
    state.cancelled = True

    status = runner._live_run_status("cancel-pending", state)

    assert status["state"] == "running"
    assert status["cancel_requested"] is True
    assert status["solver_progress"]["phase"] == "running"


def test_broker_child_exit_clears_earlier_cancel_intent_and_completes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "broker-child-exit"
    run_dir.mkdir()
    receipt = _receipt("broker-child-exit")

    class FakeBrokerProcess:
        supervision_error = None

        def poll(self):
            return 0

        def status(self):
            return {"state": "terminal", "reason": "child_exit", "child_exit_code": 0}

    state = _live_state(run_dir, poll_result=0, receipt=receipt)
    state.popen = FakeBrokerProcess()
    state.launch_strategy = "explorer_one_shot_broker"
    state.cancelled = True
    monkeypatch.setattr(runner, "BrokerProcess", FakeBrokerProcess)
    monkeypatch.setattr(
        runner,
        "qualify_native_completion",
        lambda *args: {"ok": True, "reason": "qualified_normal_stop"},
    )
    monkeypatch.setattr(runner, "collect_outputs", lambda *args, **kwargs: [])

    status = runner._live_run_status("broker-child-exit", state)

    assert status["state"] == "completed"
    assert status["cancelled"] is False
    assert status["cancel_requested"] is False
