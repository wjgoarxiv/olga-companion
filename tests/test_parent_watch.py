"""The sidecar stops when the desktop app that started it is gone (bug report 2026-11-13)."""
from __future__ import annotations

import threading

from olga_companion.parent_watch import PARENT_PID_ENV, start_parent_watch


def test_the_sidecar_stops_when_the_app_process_ends() -> None:
    stopped = threading.Event()
    watched: list[int] = []

    def app_ended(pid: int) -> bool:
        watched.append(pid)
        return True

    thread = start_parent_watch(
        stopped.set,
        environ={PARENT_PID_ENV: "4321"},
        wait_for_exit=app_ended,
        platform="win32",
    )

    assert thread is not None
    thread.join(timeout=5)
    assert watched == [4321]
    assert stopped.is_set()


def test_an_app_that_cannot_be_watched_leaves_the_sidecar_running() -> None:
    stopped = threading.Event()
    thread = start_parent_watch(
        stopped.set,
        environ={PARENT_PID_ENV: "4321"},
        wait_for_exit=lambda _pid: False,
        platform="win32",
    )
    assert thread is not None
    thread.join(timeout=5)
    assert not stopped.is_set()


def test_no_watch_without_a_parent_id_or_off_windows() -> None:
    assert start_parent_watch(lambda: None, environ={}, platform="win32") is None
    assert start_parent_watch(lambda: None, environ={PARENT_PID_ENV: "x"}, platform="win32") is None
    assert start_parent_watch(lambda: None, environ={PARENT_PID_ENV: "4321"}, platform="linux") is None
