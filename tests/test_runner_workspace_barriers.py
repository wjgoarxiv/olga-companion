from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from olga_companion import config, runner as runner_module, workspace
from olga_companion.runner import (
    execute_run,
    preview_run,
    run_status,
)

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"
BROKEN = SAMPLE_ROOT / "intentionally_broken.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def _resolvable_case(tmp_path: Path, name: str = "case.genkey") -> Path:
    """SIMPLE with its PVTFILE reference satisfied: refs ./fluid.tab, copied beside."""
    case = tmp_path / name
    text = SIMPLE.read_text()
    case.write_text(text.replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    return case


def _wait_for_final_state(run_id: str, timeout_s: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = run_status(run_id)
        if status["state"] != "running":
            return status
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not reach a final state within {timeout_s}s")


def test_workspace_switch_wins_before_single_run_barrier_with_zero_spawn_or_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old_root = tmp_path / "single-old"
    new_root = tmp_path / "single-new"
    old_root.mkdir()
    new_root.mkdir()
    source = _resolvable_case(old_root)
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    config.set_workspace_root(str(old_root))
    preview = preview_run(str(source))
    switch_holds_context = threading.Event()
    allow_switch_commit = threading.Event()
    real_commit = config.commit_workspace_context

    def blocked_commit(root: Path, generation: int) -> None:
        switch_holds_context.set()
        assert allow_switch_commit.wait(2)
        real_commit(root, generation)

    monkeypatch.setattr(config, "commit_workspace_context", blocked_commit)
    spawned = threading.Event()
    process = Mock()
    process.poll.return_value = 0
    process.wait.return_value = 0

    def observe_spawn(*args, **kwargs):
        spawned.set()
        return process

    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", observe_spawn)
    switch_errors: list[BaseException] = []
    execute_errors: list[BaseException] = []

    def capture(call, errors: list[BaseException]) -> None:
        try:
            call()
        except BaseException as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            errors.append(exc)

    switch_thread = threading.Thread(target=lambda: capture(lambda: workspace.switch_root(new_root), switch_errors))
    execute_thread = threading.Thread(
        target=lambda: capture(
            lambda: execute_run(
                str(source), approved=True, selection_id=preview["selection_id"]
            ),
            execute_errors,
        )
    )
    switch_thread.start()
    assert switch_holds_context.wait(1)
    execute_thread.start()
    assert not spawned.wait(0.1)
    allow_switch_commit.set()
    switch_thread.join(2)
    execute_thread.join(2)

    assert not switch_errors
    assert len(execute_errors) == 1
    assert "context" in str(execute_errors[0]).lower() or "preview" in str(execute_errors[0]).lower()
    assert not spawned.is_set()
    runs_root = config.sandbox_root() / "runs"
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def test_single_run_barrier_wins_and_blocks_switch_until_spawn_is_registry_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old_root = tmp_path / "launch-old"
    new_root = tmp_path / "launch-new"
    old_root.mkdir()
    new_root.mkdir()
    source = _resolvable_case(old_root)
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    config.set_workspace_root(str(old_root))
    preview = preview_run(str(source))
    spawn_entered = threading.Event()
    allow_spawn = threading.Event()
    switch_finished = threading.Event()
    process = Mock()
    process.poll.return_value = 0
    process.wait.return_value = 0

    def blocked_spawn(*args, **kwargs):
        spawn_entered.set()
        assert allow_spawn.wait(2)
        return process

    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", blocked_spawn)
    execute_results: list[dict] = []
    execute_errors: list[BaseException] = []
    switch_errors: list[BaseException] = []

    def execute() -> None:
        try:
            execute_results.append(
                execute_run(str(source), approved=True, selection_id=preview["selection_id"])
            )
        except BaseException as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            execute_errors.append(exc)

    def switch() -> None:
        try:
            workspace.switch_root(new_root)
        except BaseException as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            switch_errors.append(exc)
        finally:
            switch_finished.set()

    execute_thread = threading.Thread(target=execute)
    execute_thread.start()
    assert spawn_entered.wait(5)
    switch_thread = threading.Thread(target=switch)
    switch_thread.start()
    assert not switch_finished.wait(0.1), "workspace switch must wait for spawn and registry publication"
    allow_spawn.set()
    execute_thread.join(2)
    switch_thread.join(2)

    assert not execute_errors
    assert not switch_errors
    assert len(execute_results) == 1
    run_id = execute_results[0]["run_id"]
    with runner_module._REGISTRY_LOCK:
        assert run_id in runner_module._RUNS
        runner_module._RUNS.pop(run_id, None)
    assert workspace.context_identity()[0] == new_root.resolve()
