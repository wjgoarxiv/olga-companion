"""Stop the sidecar when the desktop app that started it is gone.

Bug report 2026-11-13: the app window was killed from outside and the sidecar kept
running in the background with no way to reach it. The app passes its process id in
OLGA_PARENT_PID; when that process ends, the sidecar stops its runs and exits.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable

from .runtime_logging import LOGGER_NAME

PARENT_PID_ENV = "OLGA_PARENT_PID"
_SYNCHRONIZE = 0x00100000
_INFINITE = 0xFFFFFFFF


def _wait_for_windows_process(pid: int) -> bool:
    """Block until the process ends; False if it could not be watched."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        kernel32.WaitForSingleObject(handle, _INFINITE)
    finally:
        kernel32.CloseHandle(handle)
    return True


def start_parent_watch(
    on_parent_exit: Callable[[], None],
    *,
    environ: dict[str, str] | None = None,
    wait_for_exit: Callable[[int], bool] | None = None,
    platform: str | None = None,
) -> threading.Thread | None:
    """Watch the parent named in the environment on native Windows; None if not watching."""
    value = (environ if environ is not None else os.environ).get(PARENT_PID_ENV, "")
    if (platform or sys.platform) != "win32" or not value.isdigit():
        return None
    pid = int(value)
    wait = wait_for_exit or _wait_for_windows_process

    def watch() -> None:
        if wait(pid):
            logging.getLogger(LOGGER_NAME).warning("parent_exited pid=%s", pid)
            on_parent_exit()

    thread = threading.Thread(target=watch, name="parent-watch", daemon=True)
    thread.start()
    return thread
