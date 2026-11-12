from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from olga_companion import runner
from olga_companion.windows_broker import (
    BROKER_PROTOCOL,
    BrokerProcess,
    qualify_native_completion,
    read_broker_status,
    request_broker_cancel,
)


def test_broker_process_ignores_explorer_exit_and_returns_exact_child_exit(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    process = BrokerProcess(
        dispatcher=dispatcher,
        run_dir=run_dir,
        request_id="request-id",
        startup_timeout_s=30,
    )

    assert process.poll() is None, (
        "Explorer dispatcher exit must never be treated as solver success"
    )
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": "request-id",
                "state": "terminal",
                "child_exit_code": 57,
                "reason": "child_exit",
                "broker_pid": 10,
                "child_pid": 11,
            }
        ),
        encoding="utf-8",
    )

    assert process.poll() == 57
    assert process.wait(timeout=0.1) == 57


def test_broker_status_retries_one_transient_incomplete_atomic_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request_id = "7" * 64
    status_path = run_dir / "broker-status.json"
    status_path.write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "running",
                "child_exit_code": None,
                "reason": "child_running",
                "broker_pid": 10,
                "child_pid": 11,
                "updated_utc": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    attempts = 0

    def transient_read(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal attempts
        if path == status_path and attempts == 0:
            attempts += 1
            return '{"protocol":'
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient_read)

    status = read_broker_status(run_dir, request_id)

    assert status is not None
    assert status["state"] == "running"
    assert attempts == 1


def test_broker_process_fails_closed_when_explorer_exits_without_status(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    process = BrokerProcess(dispatcher, run_dir, "request-id", startup_timeout_s=0)

    assert process.poll() == 125
    assert "did not publish" in str(process.supervision_error)
    dispatcher.poll.assert_called()


def test_broker_process_fails_closed_on_stale_heartbeat_after_dispatcher_exit(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    request_id = "6" * 64
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "running",
                "child_exit_code": None,
                "reason": "child_running",
                "broker_pid": 10,
                "child_pid": 11,
                "updated_utc": "2000-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    process = BrokerProcess(dispatcher, run_dir, request_id, startup_timeout_s=30)

    assert process.poll() == 125
    assert process.wait(timeout=0.1) == 125
    assert "heartbeat" in str(process.supervision_error).lower()
    cancel = json.loads((run_dir / "broker-cancel.json").read_text(encoding="utf-8"))
    assert cancel["request_id"] == request_id
    assert cancel["reason"] == "killed"


@pytest.mark.parametrize("invalid_exit", [False, True, 2147483648, -2147483649])
def test_broker_process_rejects_non_int32_terminal_exit_codes(
    tmp_path: Path,
    invalid_exit: bool | int,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    request_id = "4" * 64
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "terminal",
                "child_exit_code": invalid_exit,
                "reason": "child_exit",
                "broker_pid": 10,
                "child_pid": 11,
            }
        ),
        encoding="utf-8",
    )
    process = BrokerProcess(dispatcher, run_dir, request_id)

    assert process.poll() == 125
    assert process.supervision_error is not None
    assert process.poll() != 0


def test_broker_process_persists_cancel_atomically(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    process = BrokerProcess(dispatcher, run_dir, "request-id", startup_timeout_s=30)

    process.terminate()

    cancel = json.loads((run_dir / "broker-cancel.json").read_text(encoding="utf-8"))
    assert cancel["protocol"] == BROKER_PROTOCOL
    assert cancel["request_id"] == "request-id"
    assert cancel["reason"] == "cancelled"


def test_public_broker_cancel_helper_writes_bound_bounded_tombstone(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request_id = "a" * 64

    request_broker_cancel(run_dir, request_id, reason="cancelled")

    cancel_path = run_dir / "broker-cancel.json"
    assert cancel_path.stat().st_size < 64 * 1024
    cancel = json.loads(cancel_path.read_text(encoding="utf-8"))
    assert cancel["protocol"] == BROKER_PROTOCOL
    assert cancel["request_id"] == request_id
    assert cancel["reason"] == "cancelled"


def test_native_completion_requires_fresh_nonempty_matching_normal_stop(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case.genkey"
    case.write_text("CASE\n")
    output = tmp_path / "case.out"
    output.write_text(
        "VERSION : OLGA 2022.1.0.1\n"
        "INPUT FILE : case.genkey\n"
        "**************** NORMAL STOP IN EXECUTION ****************\n"
    )
    started_ns = output.stat().st_mtime_ns

    assert qualify_native_completion(tmp_path, "case.genkey", started_ns)["ok"] is True
    assert (
        qualify_native_completion(tmp_path, "case.genkey", started_ns + 1)["ok"]
        is False
    )
    output.write_text("INPUT FILE : other.genkey\nNORMAL STOP IN EXECUTION\n")
    assert qualify_native_completion(tmp_path, "case.genkey", 0)["ok"] is False
    output.write_text(
        "INPUT FILE : other.genkey\n"
        "case.genkey mentioned elsewhere\n"
        "NORMAL STOP IN EXECUTION\n"
    )
    assert qualify_native_completion(tmp_path, "case.genkey", 0)["ok"] is False


@pytest.mark.parametrize("flag", ["cancelled", "timed_out"])
def test_live_running_broker_status_never_erases_python_terminal_request_flags(
    tmp_path: Path,
    flag: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request_id = "5" * 64
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "running",
                "child_exit_code": None,
                "reason": "child_running",
                "broker_pid": 10,
                "child_pid": 11,
                "updated_utc": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    process = BrokerProcess(dispatcher, run_dir, request_id)
    state = runner._RunState(
        popen=process,
        run_dir=run_dir,
        log_path=run_dir / "run.log",
        command=["engine.exe", "case.genkey"],
        detection={"kind": "engine"},
        selection_id="selection",
        validation_valid=True,
        timeout_s=30,
        started_monotonic=0,
        timer=Mock(),
        receipt={},
        launch_strategy="explorer_one_shot_broker",
        staged_case_name="case.genkey",
    )
    setattr(state, flag, True)

    status = runner._live_run_status("run", state)

    assert status[flag] is True
