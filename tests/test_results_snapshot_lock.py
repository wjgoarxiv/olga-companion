"""A long results walk must not hold the context lock (review 2026-11-27)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from olga_companion import config, runner, workspace
from olga_companion.agent import approvals, tools

BODY = b"'OLGA 2022.1.0' synthetic result body\n"
WAIT = 5.0


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, name in ((first, "a.tpl"), (second, "b.tpl")):
        root.mkdir()
        (root / name).write_bytes(BODY)
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(config, "sandbox_root", lambda: tmp_path / "sandbox")
    config.set_workspace_root(str(first))
    return first, second


class SlowWalk:
    """Make the workspace scan block until released, like a 20000-entry walk."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, on_walk=None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.walks = 0
        real = workspace.scan_workspace_results

        def slow(root, **kwargs):
            self.walks += 1
            first = self.walks == 1
            self.entered.set()
            if first and on_walk:
                on_walk()
            if first:
                assert self.release.wait(WAIT)
            return real(root, **kwargs)

        monkeypatch.setattr(workspace, "scan_workspace_results", slow)


def _start(target) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = target()
        except BaseException as exc:  # noqa: BLE001 - handed back to the test
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def _finishes_during_walk(slow: SlowWalk, target) -> bool:
    """Run target while the walk is blocked; True when it finished before the walk was released."""
    walker, _ = _start(workspace.results_snapshot)
    assert slow.entered.wait(WAIT)
    other, _ = _start(target)
    other.join(1.0)
    done = not other.is_alive()
    slow.release.set()
    other.join(WAIT)
    walker.join(WAIT)
    return done


def test_a_context_switch_is_not_held_up_by_the_walk(roots, monkeypatch):
    _first, second = roots
    slow = SlowWalk(monkeypatch)
    assert _finishes_during_walk(slow, lambda: workspace.switch_root(second))


def test_the_approval_path_is_not_held_up_by_the_walk(roots, monkeypatch):
    slow = SlowWalk(monkeypatch)
    generation = workspace.context_generation()

    def approve():
        with workspace.expected_context(generation):
            return True

    assert _finishes_during_walk(slow, approve)


def test_context_identity_is_not_held_up_by_the_walk(roots, monkeypatch):
    slow = SlowWalk(monkeypatch)
    assert _finishes_during_walk(slow, workspace.context_identity)


def test_the_active_case_read_is_not_held_up_by_the_walk(roots, monkeypatch):
    slow = SlowWalk(monkeypatch)
    assert _finishes_during_walk(slow, workspace.active_path)


@pytest.mark.parametrize("stop", ["run_cancel", "sweep_cancel"])
def test_a_stop_through_the_agent_tool_is_not_held_up_by_the_walk(roots, monkeypatch, stop):
    from olga_companion import sweep_execution

    monkeypatch.setattr(runner, "cancel_run", lambda run_id: {"run_id": run_id, "cancelled": True})
    monkeypatch.setattr(sweep_execution, "cancel_sweep", lambda sweep_id: {"sweep_id": sweep_id})
    args = {"run_id": "abc123def456"} if stop == "run_cancel" else {"sweep_id": "sweep_abc123"}
    token = approvals.mint(
        stop,
        tools.approval_payload(stop, args),
        context_generation=workspace.context_generation(),
    )["token"]
    slow = SlowWalk(monkeypatch)
    cancel = lambda: tools.dispatch(  # noqa: E731
        stop, {**args, "approval_token": token, "idempotency_key": "pending-action"}
    )
    assert _finishes_during_walk(slow, cancel)


def test_the_snapshot_belongs_to_the_root_it_returns_after_a_switch_mid_walk(roots, monkeypatch):
    first, second = roots
    slow = SlowWalk(monkeypatch)
    walker, box = _start(workspace.results_snapshot)
    assert slow.entered.wait(WAIT)
    switched = workspace.switch_root(second)
    slow.release.set()
    walker.join(WAIT)

    snapshot = box["value"]
    assert snapshot["root"] == str(second.resolve()) == switched["root"]
    assert snapshot["generation"] == switched["generation"]
    assert [item["name"] for item in snapshot["results"]] == ["b.tpl"]


def test_a_snapshot_with_no_switch_is_walked_once(roots, monkeypatch):
    first, _second = roots
    slow = SlowWalk(monkeypatch)
    slow.release.set()
    snapshot = workspace.results_snapshot()
    assert slow.walks == 1
    assert snapshot["root"] == str(first.resolve())
    assert [item["name"] for item in snapshot["results"]] == ["a.tpl"]


def test_a_workspace_that_keeps_moving_still_answers_with_one_roots_results(roots, monkeypatch):
    # Callers such as GET /api/workspace/results have no stale-error handling, so the snapshot
    # answers even when both unlocked walks were overtaken by a switch.
    first, second = roots
    switches = iter([second, first])
    real = workspace.scan_workspace_results
    walks: list[Path] = []

    def switching_twice(root, **kwargs):
        found = real(root, **kwargs)
        walks.append(Path(root))
        target = next(switches, None)
        if target is not None:
            workspace.switch_root(target)
        return found

    monkeypatch.setattr(workspace, "scan_workspace_results", switching_twice)
    snapshot = workspace.results_snapshot()

    assert len(walks) == 3
    assert snapshot["root"] == str(first.resolve())
    assert snapshot["generation"] == workspace.context_identity()[1]
    assert [item["name"] for item in snapshot["results"]] == ["a.tpl"]
