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


def test_cancel_after_restart_persists_bound_request_and_reconciles_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "recovered-cancel"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    request_id = "9" * 64
    write_run_record(run_dir, _broker_receipt("recovered-cancel", request_id))
    status_path = run_dir / "broker-status.json"
    status_path.write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": request_id,
                "state": "running",
                "child_exit_code": None,
                "reason": "child_running",
                "broker_pid": 301,
                "child_pid": 302,
                "updated_utc": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )
    completed = False

    def complete_after_cancel(_seconds: float) -> None:
        nonlocal completed
        if completed:
            return
        cancel = json.loads((run_dir / "broker-cancel.json").read_text(encoding="utf-8"))
        assert cancel["request_id"] == request_id
        status_path.write_text(
            json.dumps(
                {
                    "protocol": BROKER_PROTOCOL,
                    "request_id": request_id,
                    "state": "terminal",
                    "child_exit_code": 1223,
                    "reason": "cancelled",
                    "broker_pid": 301,
                    "child_pid": 302,
                }
            ),
            encoding="utf-8",
        )
        completed = True

    monkeypatch.setattr(runner.time, "sleep", complete_after_cancel)

    cancelled = runner.cancel_run("recovered-cancel")

    tombstone = json.loads((run_dir / "broker-cancel.json").read_text(encoding="utf-8"))
    assert tombstone["protocol"] == BROKER_PROTOCOL
    assert tombstone["request_id"] == request_id
    assert tombstone["reason"] == "cancelled"
    assert cancelled["state"] == "cancelled"
    assert cancelled["ok"] is False
    assert cancelled["exit_code"] == 1223
    assert cancelled["failure"]["code"] == "run_cancelled"
    assert "You cancelled this run" in cancelled["failure"]["detail"]
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))[
        "phase"
    ] == "terminal"


def test_cancel_after_restart_does_not_touch_direct_recovery_unknown_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "direct-orphan"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    receipt = _broker_receipt("direct-orphan", "8" * 64)
    receipt.pop("broker_run")
    receipt["launch_strategy"] = "direct"
    write_run_record(run_dir, receipt)

    status = runner.cancel_run("direct-orphan")

    assert status["state"] == "recovery_unknown"
    assert status["ok"] is False
    assert not (run_dir / "broker-cancel.json").exists()


def test_cancel_after_restart_bounds_wait_when_broker_status_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    run_dir = sandbox / "runs" / "missing-status-cancel"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    request_id = "7" * 64
    write_run_record(run_dir, _broker_receipt("missing-status-cancel", request_id))
    monotonic = iter((100.0, 111.0))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(monotonic))

    status = runner.cancel_run("missing-status-cancel")

    assert status["state"] == "supervision_unknown"
    assert status["ok"] is False
    assert status["cancel_requested"] is True
    assert json.loads((run_dir / "broker-cancel.json").read_text(encoding="utf-8"))[
        "request_id"
    ] == request_id
