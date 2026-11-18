from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from olga_companion import runner
from olga_companion.genkey_static import OlgaInputError


class _LaunchFailure(RuntimeError):
    """Synthetic launch failure used to verify claim release."""


def test_same_selection_allows_exactly_one_launch_body(monkeypatch: pytest.MonkeyPatch) -> None:
    selection_id = "reviewed-selection-concurrent"
    callers_ready = threading.Barrier(3)
    launch_entered = threading.Event()
    release_launch = threading.Event()
    duplicate_rejected = threading.Event()
    launched: list[str] = []
    results: list[dict] = []
    errors: list[Exception] = []

    def fake_launch(*args, **kwargs):
        launched.append(str(kwargs["selection_id"]))
        launch_entered.set()
        assert release_launch.wait(timeout=2)
        return {"run_id": "winning-run"}

    monkeypatch.setattr(runner, "_execute_run_claimed", fake_launch)

    def call_execute() -> None:
        callers_ready.wait(timeout=2)
        try:
            results.append(
                runner.execute_run(
                    "case.genkey",
                    approved=True,
                    selection_id=selection_id,
                )
            )
        except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — capture rejected contender
            errors.append(exc)
            duplicate_rejected.set()

    threads = [threading.Thread(target=call_execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    callers_ready.wait(timeout=2)

    assert launch_entered.wait(timeout=2)
    assert duplicate_rejected.wait(timeout=2)
    release_launch.set()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert launched == [selection_id]
    assert results == [{"run_id": "winning-run"}]
    assert len(errors) == 1
    assert isinstance(errors[0], OlgaInputError)
    assert "monitor/cancel" in str(errors[0]).lower()


def test_failed_launch_body_releases_selection_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def fail_then_succeed(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _LaunchFailure("start failed")
        return {"run_id": "retry-run"}

    monkeypatch.setattr(runner, "_execute_run_claimed", fail_then_succeed)

    with pytest.raises(_LaunchFailure, match="start failed"):
        runner.execute_run(
            "case.genkey",
            approved=True,
            selection_id="reviewed-selection-retry",
        )

    assert runner.execute_run(
        "case.genkey",
        approved=True,
        selection_id="reviewed-selection-retry",
    ) == {"run_id": "retry-run"}
    assert attempts == 2


def test_live_existing_run_blocks_same_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    selection_id = "reviewed-selection-live"
    launch = Mock(return_value={"run_id": "must-not-launch"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)
    state = SimpleNamespace(selection_id=selection_id, popen=SimpleNamespace(poll=lambda: None))
    with runner._REGISTRY_LOCK:
        runner._RUNS["existing-live-run"] = state

    try:
        with pytest.raises(OlgaInputError, match="[Mm]onitor/cancel"):
            runner.execute_run(
                "case.genkey",
                approved=True,
                selection_id=selection_id,
            )
    finally:
        with runner._REGISTRY_LOCK:
            runner._RUNS.pop("existing-live-run", None)

    launch.assert_not_called()


def test_terminal_existing_run_permits_same_selection_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    selection_id = "reviewed-selection-terminal"
    launch = Mock(return_value={"run_id": "legitimate-rerun"})
    monkeypatch.setattr(runner, "_execute_run_claimed", launch)
    state = SimpleNamespace(selection_id=selection_id, popen=SimpleNamespace(poll=lambda: 0))
    with runner._REGISTRY_LOCK:
        runner._RUNS["existing-terminal-run"] = state

    try:
        result = runner.execute_run(
            "case.genkey",
            approved=True,
            selection_id=selection_id,
        )
    finally:
        with runner._REGISTRY_LOCK:
            runner._RUNS.pop("existing-terminal-run", None)

    assert result == {"run_id": "legitimate-rerun"}
    launch.assert_called_once()
