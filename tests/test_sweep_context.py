from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from olga_companion import config, workspace
from olga_companion.sweep_execution import execute_sweep, preview_sweep
from sweep_test_support import FAKE_OLGA, SIMPLE, _capture_error, _resolvable_case

pytestmark = pytest.mark.skipif(
    not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable"
)


def test_workspace_switch_wins_race_before_sweep_guard_and_no_child_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    old = tmp_path / "race-old"
    new = tmp_path / "race-new"
    old.mkdir()
    new.mkdir()
    base = _resolvable_case(old)
    config.set_workspace_root(str(old))
    preview = preview_sweep(str(base), ["INTEGRATION.ENDTIME=3600,7200"], "oat", 5, 30)
    switch_has_context_lock = threading.Event()
    allow_context_commit = threading.Event()
    real_commit = config.commit_workspace_context

    def blocked_commit(root: Path, generation: int):
        switch_has_context_lock.set()
        assert allow_context_commit.wait(2)
        return real_commit(root, generation)

    monkeypatch.setattr(config, "commit_workspace_context", blocked_commit)
    child_calls: list[str] = []
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run",
        lambda source, **kwargs: child_calls.append(source) or {"run_id": "unexpected"},
    )
    switch_errors: list[BaseException] = []
    execute_errors: list[BaseException] = []
    switch_thread = threading.Thread(
        target=lambda: _capture_error(lambda: workspace.switch_root(new), switch_errors)
    )
    execute_thread = threading.Thread(
        target=lambda: _capture_error(
            lambda: execute_sweep(
                preview["sweep_id"], approved=True, plan_id=preview["plan_id"]
            ),
            execute_errors,
        )
    )

    switch_thread.start()
    assert switch_has_context_lock.wait(1)
    execute_thread.start()
    time.sleep(0.1)
    allow_context_commit.set()
    switch_thread.join(2)
    execute_thread.join(2)

    assert not switch_errors
    assert len(execute_errors) == 1
    assert "Workspace context changed" in str(execute_errors[0])
    assert child_calls == []


def test_sweep_guard_wins_race_and_switch_waits_until_every_child_is_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    old = tmp_path / "guard-old"
    new = tmp_path / "guard-new"
    old.mkdir()
    new.mkdir()
    config.set_workspace_root(str(old))
    preview = preview_sweep(
        str(_resolvable_case(old)),
        ["INTEGRATION.ENDTIME=3600,7200"],
        "oat",
        5,
        30,
    )
    materializing = threading.Event()
    allow_materialization = threading.Event()
    real_materialize = __import__(
        "olga_companion.sweep_execution", fromlist=["_materialize_pvt_companions"]
    )._materialize_pvt_companions
    materialize_calls = 0

    def blocked_materialize(base: Path, case: Path) -> list[str]:
        nonlocal materialize_calls
        materialize_calls += 1
        if materialize_calls == 1:
            materializing.set()
            assert allow_materialization.wait(2)
        return real_materialize(base, case)

    child_generations: list[int] = []
    monkeypatch.setattr(
        "olga_companion.sweep_execution._materialize_pvt_companions",
        blocked_materialize,
    )
    monkeypatch.setattr(
        "olga_companion.sweep_execution.runner.execute_run",
        lambda source, **kwargs: (
            child_generations.append(workspace.context_generation())
            or {"run_id": f"run-{len(child_generations)}"}
        ),
    )
    execute_errors: list[BaseException] = []
    switch_errors: list[BaseException] = []
    switch_finished = threading.Event()
    execute_thread = threading.Thread(
        target=lambda: _capture_error(
            lambda: execute_sweep(
                preview["sweep_id"], approved=True, plan_id=preview["plan_id"]
            ),
            execute_errors,
        )
    )

    def switch() -> None:
        _capture_error(lambda: workspace.switch_root(new), switch_errors)
        switch_finished.set()

    execute_thread.start()
    assert materializing.wait(1)
    switch_thread = threading.Thread(target=switch)
    switch_thread.start()
    assert not switch_finished.wait(0.1), (
        "root switch must wait for the sweep context guard"
    )
    allow_materialization.set()
    execute_thread.join(2)
    switch_thread.join(2)

    assert not execute_errors
    assert not switch_errors
    assert child_generations == [0, 0]
    assert workspace.context_generation() == 1
