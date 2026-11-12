from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Final, Protocol

_TERMINATION_GRACE_SECONDS: Final = 3.0
_GROUP_POLL_SECONDS: Final = 0.05


class ProcessHandle(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


def _group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def _terminate_process_group(process: ProcessHandle, process_group_id: int) -> None:
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
    while True:
        process.poll()
        if not _group_exists(process_group_id):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_GROUP_POLL_SECONDS, remaining))

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return
    if process.poll() is None:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)


def _terminate_single_process(process: ProcessHandle) -> None:
    process.terminate()
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)


def terminate_process(process: ProcessHandle, *, process_group_id: int | None) -> None:
    if process_group_id is not None:
        _terminate_process_group(process, process_group_id)
        return
    if process.poll() is not None:
        return
    _terminate_single_process(process)
