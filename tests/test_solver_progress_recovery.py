from __future__ import annotations

import threading
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
def test_recovered_broker_terminal_receipt_persistence_failure_remains_pollable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "runs" / "receipt-sharing-broker"
    run_dir.mkdir(parents=True)
    receipt = _receipt("receipt-sharing-broker")
    receipt["broker_run"] = {
        "protocol": runner.BROKER_PROTOCOL,
        "request_id": "receipt-request",
        "started_wall_ns": 1,
        "cancel_name": "broker-cancel.json",
    }
    write_run_record(run_dir, receipt)
    terminal_evidence = {"state": "terminal", "reason": "child_exit", "child_exit_code": 0}
    monkeypatch.setattr(runner, "sandbox_root", lambda: tmp_path)
    monkeypatch.setattr(runner, "read_broker_status", lambda *args: terminal_evidence)
    monkeypatch.setattr(
        runner,
        "qualify_native_completion",
        lambda *args: {"ok": True, "reason": "qualified_normal_stop"},
    )
    monkeypatch.setattr(runner, "collect_outputs", lambda *args, **kwargs: [])
    real_write = runner.write_run_record
    attempts = 0
    successes = 0

    def sharing_failure(path: Path, record: dict) -> None:
        nonlocal attempts, successes
        if record.get("phase") == "terminal":
            attempts += 1
            if attempts <= 2:
                raise OSError("run.json sharing violation")
            successes += 1
        real_write(path, record)

    monkeypatch.setattr(runner, "write_run_record", sharing_failure)
    first = runner.run_status("receipt-sharing-broker")
    second = runner.run_status("receipt-sharing-broker")
    before_success = load_run_record(run_dir)
    terminal = runner.run_status("receipt-sharing-broker")

    assert [first["state"], second["state"]] == ["finalizing", "finalizing"]
    assert first["broker_status"] == terminal_evidence
    assert first["native_completion"]["ok"] is True
    assert first["exit_code"] == 0
    assert before_success["phase"] == "running"
    assert terminal["state"] == "completed"
    assert successes == 1
    assert load_run_record(run_dir)["phase"] == "terminal"


def test_concurrent_live_terminal_polls_retry_receipt_sharing_and_persist_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "receipt-sharing-concurrent"
    run_dir.mkdir()
    receipt = _receipt("receipt-sharing-concurrent")
    write_run_record(run_dir, receipt)
    state = _live_state(run_dir, poll_result=0, receipt=receipt)
    real_write = runner.write_run_record
    write_lock = threading.Lock()
    attempts = 0
    successes = 0

    def sharing_failure(path: Path, record: dict) -> None:
        nonlocal attempts, successes
        if record.get("phase") == "terminal":
            with write_lock:
                attempts += 1
                if attempts <= 3:
                    raise PermissionError("shared")
                successes += 1
        real_write(path, record)

    monkeypatch.setattr(runner, "write_run_record", sharing_failure)
    statuses: list[dict] = []
    errors: list[BaseException] = []

    def poll() -> None:
        try:
            statuses.append(runner._live_run_status("receipt-sharing-concurrent", state))
        except BaseException as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            errors.append(exc)

    threads = [threading.Thread(target=poll) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()

    assert errors == []
    assert {status["state"] for status in statuses} == {"finalizing", "completed"}
    assert successes == 1
    assert load_run_record(run_dir)["phase"] == "terminal"
