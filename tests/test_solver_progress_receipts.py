from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from olga_companion import runner
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
def test_terminal_output_sharing_returns_finalizing_then_persists_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "finalizing"
    run_dir.mkdir()
    receipt = _receipt("finalizing")
    write_run_record(run_dir, receipt)
    state = _live_state(run_dir, poll_result=0, receipt=receipt)
    attempts = 0
    terminal_writes = 0
    real_write = runner.write_run_record

    def transient_collect(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("native sharing violation")
        return []

    def count_write(path: Path, record: dict) -> None:
        nonlocal terminal_writes
        if record.get("phase") == "terminal":
            terminal_writes += 1
        real_write(path, record)

    monkeypatch.setattr(runner, "collect_outputs", transient_collect)
    monkeypatch.setattr(runner, "write_run_record", count_write)

    pending = runner._live_run_status("finalizing", state)
    still_running_receipt = load_run_record(run_dir)
    terminal = runner._live_run_status("finalizing", state)

    assert pending["state"] == "finalizing"
    assert pending["cancelled"] is False
    assert pending["cancel_requested"] is False
    assert pending["collection_pending"] is True
    assert still_running_receipt["phase"] == "running"
    assert terminal["state"] == "completed"
    assert terminal_writes == 1


def test_broker_recovery_retries_transient_terminal_collection_without_false_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "broker-finalizing"
    run_dir.mkdir(parents=True)
    receipt = _receipt("broker-finalizing")
    receipt["broker_run"] = {
        "protocol": runner.BROKER_PROTOCOL,
        "request_id": "request-1",
        "started_wall_ns": 1,
        "cancel_name": "broker-cancel.json",
    }
    receipt["cancelled"] = True
    write_run_record(run_dir, receipt)
    (run_dir / "broker-cancel.json").write_text("{}", encoding="utf-8")
    broker_terminal = {"state": "terminal", "reason": "child_exit", "child_exit_code": 0}
    attempts = 0

    def transient_qualification(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("out file still shared")
        return {"ok": True, "reason": "qualified_normal_stop"}

    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path)
    monkeypatch.setattr(runner, "read_broker_status", lambda *args: broker_terminal)
    monkeypatch.setattr(runner, "qualify_native_completion", transient_qualification)
    monkeypatch.setattr(runner, "collect_outputs", lambda *args, **kwargs: [])

    pending = runner.run_status("broker-finalizing")
    before_retry = load_run_record(run_dir)
    terminal = runner.run_status("broker-finalizing")

    assert pending["state"] == "finalizing"
    assert before_retry["phase"] == "running"
    assert pending["cancelled"] is False
    assert pending["cancel_requested"] is False
    assert terminal["state"] == "completed"
    assert terminal["cancelled"] is False
    assert terminal["cancel_requested"] is False
    assert load_run_record(run_dir)["phase"] == "terminal"


def test_live_terminal_receipt_persistence_failure_returns_finalizing_until_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "receipt-sharing-live"
    run_dir.mkdir()
    receipt = _receipt("receipt-sharing-live")
    write_run_record(run_dir, receipt)
    state = _live_state(run_dir, poll_result=0, receipt=receipt)
    real_write = runner.write_run_record
    terminal_attempts = 0
    terminal_successes = 0

    def sharing_failure(path: Path, record: dict) -> None:
        nonlocal terminal_attempts, terminal_successes
        if record.get("phase") == "terminal":
            terminal_attempts += 1
            if terminal_attempts <= 2:
                raise PermissionError("run.json is temporarily shared")
            terminal_successes += 1
        real_write(path, record)

    monkeypatch.setattr(runner, "write_run_record", sharing_failure)
    first = runner._live_run_status("receipt-sharing-live", state)
    second = runner._live_run_status("receipt-sharing-live", state)
    before_success = load_run_record(run_dir)
    terminal = runner._live_run_status("receipt-sharing-live", state)
    repeated = runner._live_run_status("receipt-sharing-live", state)

    assert [first["state"], second["state"]] == ["finalizing", "finalizing"]
    assert first["exit_code"] == second["exit_code"] == 0
    assert first["collection_pending"] is True
    assert before_success["phase"] == "running"
    assert terminal["state"] == repeated["state"] == "completed"
    assert terminal_successes == 1
    assert load_run_record(run_dir)["phase"] == "terminal"
