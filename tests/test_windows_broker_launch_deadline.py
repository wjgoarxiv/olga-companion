from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from olga_companion import windows_broker_process
from olga_companion.windows_broker import BROKER_PROTOCOL, BrokerProcess


def _write_running_status(run_dir: Path, request_id: str) -> Path:
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
    return status_path


def test_valid_launch_survives_transient_status_absence_after_deadline(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request_id = "9" * 64
    status_path = _write_running_status(run_dir, request_id)
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    process = BrokerProcess(dispatcher, run_dir, request_id, startup_timeout_s=0)

    assert process.poll() is None
    status_path.unlink()

    assert process.poll() is None
    assert process.supervision_error is None
    assert not (run_dir / "broker-cancel.json").exists()


def test_missing_status_fails_closed_after_cached_heartbeat_becomes_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request_id = "8" * 64
    status_path = _write_running_status(run_dir, request_id)
    dispatcher = Mock()
    dispatcher.poll.return_value = 0
    process = BrokerProcess(dispatcher, run_dir, request_id, startup_timeout_s=0)

    assert process.poll() is None
    status_path.unlink()
    monkeypatch.setattr(
        windows_broker_process,
        "broker_heartbeat_is_live",
        lambda _value: False,
    )

    assert process.poll() == 125
    assert "heartbeat" in str(process.supervision_error).lower()
    assert (run_dir / "broker-cancel.json").exists()
