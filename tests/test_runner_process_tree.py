from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from olga_companion import runner


def _process_state(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except FileNotFoundError:
        return None


def _spawn_process_tree() -> tuple[subprocess.Popen[str], int]:
    child_code = (
        "import os, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print(os.getpid(), flush=True); "
        "time.sleep(300)"
    )
    leader_code = (
        "import subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}], "
        "stdout=subprocess.PIPE, text=True); "
        "print(child.stdout.readline(), end='', flush=True); "
        "time.sleep(300)"
    )
    leader = subprocess.Popen(
        [sys.executable, "-c", leader_code],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert leader.stdout is not None
    return leader, int(leader.stdout.readline().strip())


def _assert_process_stops(pid: int) -> None:
    deadline = time.monotonic() + 3
    state = _process_state(pid)
    while state not in {None, "Z"} and time.monotonic() < deadline:
        time.sleep(0.05)
        state = _process_state(pid)
    assert state in {None, "Z"}, f"descendant {pid} survived in state {state}"


def _clean_process_tree(leader: subprocess.Popen[str]) -> None:
    try:
        os.killpg(leader.pid, signal.SIGKILL)
    except ProcessLookupError:
        leader.poll()
    try:
        leader.wait(timeout=3)
    except subprocess.TimeoutExpired:
        leader.kill()
        leader.wait(timeout=3)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_kill_terminates_descendant_when_leader_exits_on_sigterm() -> None:
    leader, child_pid = _spawn_process_tree()

    try:
        runner._kill(SimpleNamespace(popen=leader))
        _assert_process_stops(child_pid)
    finally:
        _clean_process_tree(leader)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_kill_terminates_descendant_after_leader_already_exited() -> None:
    leader, child_pid = _spawn_process_tree()

    try:
        leader.terminate()
        leader.wait(timeout=3)
        assert _process_state(child_pid) not in {None, "Z"}

        runner._kill(SimpleNamespace(popen=leader))

        _assert_process_stops(child_pid)
    finally:
        _clean_process_tree(leader)
