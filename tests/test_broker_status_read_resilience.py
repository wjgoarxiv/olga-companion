"""Broker status reads must survive the Windows atomic-replace window.

The broker publishes status atomically (temp file + File.Replace), so a failed
read here is the transient sharing window rather than corrupt content. A false
"malformed" verdict is fatal — it cancels a healthy run — so the reader retries
across a budget before failing closed.
"""
from __future__ import annotations

import json

import pytest

from olga_companion import windows_broker_status as status_mod
from olga_companion.windows_broker_protocol import BROKER_PROTOCOL, STATUS_NAME

REQUEST_ID = "a" * 64


def _write_status(run_dir, **overrides):
    payload = {
        "protocol": BROKER_PROTOCOL,
        "request_id": REQUEST_ID,
        "state": "running",
        "reason": "child_running",
        "broker_pid": 1234,
        "child_pid": 5678,
    }
    payload.update(overrides)
    path = run_dir / STATUS_NAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fail_reads_then_succeed(monkeypatch, failures: int):
    """Make the first ``failures`` reads raise like a Windows sharing violation."""
    from pathlib import Path

    original = Path.read_text
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        if self.name == STATUS_NAME and calls["n"] < failures:
            calls["n"] += 1
            raise OSError(32, "The process cannot access the file")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    return calls


def test_transient_read_failures_inside_the_budget_still_yield_status(
    tmp_path, monkeypatch
):
    _write_status(tmp_path)
    calls = _fail_reads_then_succeed(monkeypatch, status_mod._STATUS_READ_ATTEMPTS - 1)
    monkeypatch.setattr(status_mod.time, "sleep", lambda _seconds: None)

    value = status_mod.read_broker_status(tmp_path, REQUEST_ID)

    assert value is not None
    assert value["state"] == "running"
    assert calls["n"] == status_mod._STATUS_READ_ATTEMPTS - 1


def test_read_failures_beyond_the_budget_still_fail_closed(tmp_path, monkeypatch):
    _write_status(tmp_path)
    _fail_reads_then_succeed(monkeypatch, status_mod._STATUS_READ_ATTEMPTS)
    monkeypatch.setattr(status_mod.time, "sleep", lambda _seconds: None)

    with pytest.raises(ValueError, match="malformed"):
        status_mod.read_broker_status(tmp_path, REQUEST_ID)


def test_budget_is_wide_enough_to_outlast_a_repeated_replace_window():
    # Two attempts 10 ms apart was observed cancelling a healthy run.
    assert status_mod._STATUS_READ_ATTEMPTS >= 4


def test_identity_and_state_checks_are_not_weakened_by_the_retry(tmp_path):
    _write_status(tmp_path, request_id="b" * 64)
    with pytest.raises(ValueError, match="identity"):
        status_mod.read_broker_status(tmp_path, REQUEST_ID)

    _write_status(tmp_path, state="bogus")
    with pytest.raises(ValueError, match="invalid state"):
        status_mod.read_broker_status(tmp_path, REQUEST_ID)


def test_terminal_status_still_requires_a_signed_exit_code(tmp_path):
    _write_status(tmp_path, state="terminal", child_exit_code=None)

    with pytest.raises(ValueError, match="exit code"):
        status_mod.read_broker_status(tmp_path, REQUEST_ID)


def test_missing_status_file_is_not_an_error(tmp_path):
    assert status_mod.read_broker_status(tmp_path, REQUEST_ID) is None


def test_budget_outlasts_the_brokers_own_replace_retry():
    # The broker retries File.Replace for about a second while a reader holds the file.
    # A 150 ms read budget lost that race and cancelled a healthy 1,481-section run as
    # "malformed" 50 s in; the read budget must cover the broker's retry window.
    total = sum(status_mod._STATUS_READ_BACKOFF_S * 2**attempt for attempt in range(status_mod._STATUS_READ_ATTEMPTS - 1))
    assert total >= 1.0
    assert total < status_mod.DEFAULT_HEARTBEAT_TIMEOUT_S
