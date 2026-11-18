"""A broker run whose end is proven by other means is closed, so it stops blocking updates.

Owner report 2026-11-17: installing 0.1.12 was refused because an old run stayed
"supervision_unknown" forever. The broker runs OLGA in a kill-on-close job, so once the
broker process is gone OLGA is gone too; and a broker that never wrote a status refuses to
start after a persisted cancel. Every other unproven case still blocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from olga_companion import runner, windows_broker_status
from olga_companion.run_records import write_run_record
from olga_companion.windows_broker import BROKER_PROTOCOL

from test_windows_broker_restart import _broker_receipt

REQUEST = "a1" * 32


def _iso(delta_s: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def run_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    path = sandbox / "runs" / "old-run"
    path.mkdir(parents=True)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    write_run_record(path, _broker_receipt("old-run", REQUEST))
    return path


def _status(run_dir: Path, *, state: str = "running", updated: float = -3600) -> None:
    (run_dir / "broker-status.json").write_text(
        json.dumps(
            {
                "protocol": BROKER_PROTOCOL,
                "request_id": REQUEST,
                "state": state,
                "child_exit_code": None,
                "reason": "child_running",
                "broker_pid": 4242,
                "child_pid": 4343,
                "started_utc": _iso(-4000),
                "updated_utc": _iso(updated),
            }
        ),
        encoding="utf-8",
    )


def _cancel(run_dir: Path, age_s: float) -> None:
    (run_dir / "broker-cancel.json").write_text(
        json.dumps({"protocol": BROKER_PROTOCOL, "request_id": REQUEST, "reason": "cancelled", "requested_utc": _iso(-age_s)}),
        encoding="utf-8",
    )


def _broker(monkeypatch: pytest.MonkeyPatch, alive: bool | None) -> list[tuple]:
    calls: list[tuple] = []

    def probe(pid: int, started_utc: str | None) -> bool | None:
        calls.append((pid, started_utc))
        return alive

    monkeypatch.setattr(runner, "broker_process_alive", probe)
    return calls


def test_a_gone_broker_with_a_normal_stop_is_closed_as_completed(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _status(run_dir)
    calls = _broker(monkeypatch, False)
    (run_dir / "case.out").write_text(
        "INPUT FILE : case.genkey\n**************** NORMAL STOP IN EXECUTION ****************\n"
    )

    status = runner.run_status("old-run")

    assert calls and calls[0][0] == 4242
    assert status["state"] == "completed"
    persisted = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "terminal"
    assert runner.begin_update_gate("gone-ok")["safe"] is True
    runner.release_update_gate("gone-ok")


def test_a_gone_broker_without_a_normal_stop_is_closed_as_interrupted(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _status(run_dir)
    _broker(monkeypatch, False)

    status = runner.run_status("old-run")

    assert status["state"] == "failed"
    assert status["ok"] is False
    assert status["failure"]["code"] == "run_interrupted"
    assert runner.begin_update_gate("gone-failed")["safe"] is True
    runner.release_update_gate("gone-failed")


@pytest.mark.parametrize("alive", [True, None])
def test_a_broker_that_may_still_be_alive_keeps_blocking(run_dir: Path, monkeypatch: pytest.MonkeyPatch, alive: bool | None) -> None:
    _status(run_dir)
    _broker(monkeypatch, alive)

    assert runner.run_status("old-run")["state"] == "supervision_unknown"
    gate = runner.begin_update_gate("maybe-alive")
    assert gate["safe"] is False
    assert gate["blocking"] == [{"run_id": "old-run", "state": "supervision_unknown"}]


def test_a_future_heartbeat_is_not_proof_even_with_the_broker_gone(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _status(run_dir, updated=+3600)
    _broker(monkeypatch, False)

    assert runner.run_status("old-run")["state"] == "supervision_unknown"


def test_a_broker_that_never_wrote_a_status_is_closed_once_its_cancel_has_waited(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _broker(monkeypatch, None)
    _cancel(run_dir, age_s=120)

    status = runner.run_status("old-run")

    assert status["state"] == "cancelled"
    assert status["ok"] is False
    assert runner.begin_update_gate("never-started")["safe"] is True
    runner.release_update_gate("never-started")


def test_a_fresh_cancel_without_a_status_still_blocks(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _broker(monkeypatch, None)
    _cancel(run_dir, age_s=5)

    assert runner.run_status("old-run")["state"] == "supervision_unknown"


def test_a_cancel_for_another_request_is_ignored(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _broker(monkeypatch, None)
    (run_dir / "broker-cancel.json").write_text(
        json.dumps({"protocol": BROKER_PROTOCOL, "request_id": "b2" * 32, "reason": "cancelled", "requested_utc": _iso(-120)}),
        encoding="utf-8",
    )

    assert runner.run_status("old-run")["state"] == "supervision_unknown"


def test_process_probe_has_no_answer_off_windows() -> None:
    assert windows_broker_status.broker_process_alive(1, None, platform="linux") is None
