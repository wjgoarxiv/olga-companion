from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeAlias

import pytest

from olga_companion import runner
from olga_companion.run_records import write_run_record
from olga_companion.windows_broker import BROKER_PROTOCOL

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


def _broker_receipt(run_id: str, request_id: str) -> JsonObject:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "phase": "running",
        "state": "running",
        "source": {
            "name": "original.genkey",
            "resolved_path": "/source/original.genkey",
            "sha256": "a" * 64,
            "staged_sha256": "b" * 64,
        },
        "companions": [],
        "runtime": {
            "candidate_id": "runtime_native",
            "runtime_id": "runtime_native",
            "version": "2022.1.0",
            "kind": "engine",
            "exe": "C:/OLGA/OLGA-2022.1.0.exe",
        },
        "selection_id": "selection",
        "validation": {"valid": True, "command": {}},
        "timestamps": {
            "prepared_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:01Z",
            "finished_at": None,
        },
        "command": ["C:/OLGA/OLGA-2022.1.0.exe", "case.genkey"],
        "exit_code": None,
        "failure": None,
        "outputs": [],
        "timed_out": False,
        "cancelled": False,
        "ok": False,
        "engine_failed": False,
        "validation_valid": True,
        "elapsed_ms": 0,
        "log_tail": "",
        "launch_strategy": "explorer_one_shot_broker",
        "staged_case_name": "case.genkey",
        "broker_run": {
            "request_id": request_id,
            "protocol": BROKER_PROTOCOL,
            "broker_sha256": "c" * 64,
            "status_name": "broker-status.json",
            "cancel_name": "broker-cancel.json",
            "started_wall_ns": 0,
        },
    }


def test_restart_reconciles_terminal_broker_status_into_v1_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "broker-run"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    request_id = "d" * 64
    write_run_record(run_dir, _broker_receipt("broker-run", request_id))
    (run_dir / "case.out").write_text(
        "INPUT FILE : case.genkey\n"
        "**************** NORMAL STOP IN EXECUTION ****************\n"
    )
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "terminal",
                "child_exit_code": 0,
                "reason": "child_exit",
                "broker_pid": 101,
                "child_pid": 102,
            }
        ),
        encoding="utf-8",
    )

    status = runner.run_status("broker-run")

    assert status["state"] == "completed"
    assert status["ok"] is True
    assert status["exit_code"] == 0
    assert status["recovered_from_receipt"] is True
    persisted = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "terminal"
    assert persisted["broker_status"]["child_pid"] == 102


def test_restart_never_infers_success_when_broker_status_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "missing-broker"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    write_run_record(run_dir, _broker_receipt("missing-broker", "e" * 64))

    status = runner.run_status("missing-broker")

    assert status["state"] == "supervision_unknown"
    assert status["ok"] is False
    assert "interrupted" in status["recovery"].lower()


def test_restart_reports_recent_broker_heartbeat_as_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "live-broker"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    request_id = "f" * 64
    write_run_record(run_dir, _broker_receipt("live-broker", request_id))
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "running",
                "child_exit_code": None,
                "reason": "child_running",
                "broker_pid": 201,
                "child_pid": 202,
                "updated_utc": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )

    status = runner.run_status("live-broker")

    assert status["state"] == "running"
    assert status["ok"] is False
    assert status["recovered_from_receipt"] is True
    assert "heartbeat" in status["recovery"].lower()


def test_restart_rejects_far_future_broker_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "future-broker"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    request_id = "3" * 64
    write_run_record(run_dir, _broker_receipt("future-broker", request_id))
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "running",
                "child_exit_code": None,
                "reason": "child_running",
                "broker_pid": 201,
                "child_pid": 202,
                "updated_utc": "2999-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    status = runner.run_status("future-broker")

    assert status["state"] == "supervision_unknown"
    assert status["ok"] is False
    assert "heartbeat" in status["recovery"].lower()
