"""Cross-process refresh lock for the app-scoped Codex credential cache."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from .codex_oauth_models import CodexAuthError

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class InterprocessRefreshLock:
    """Advisory file lock released automatically if a sidecar exits."""

    def __init__(
        self,
        path: Path,
        *,
        timeout: float = 45.0,
        poll_interval: float = 0.05,
    ) -> None:
        self._path = path
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._handle: BinaryIO | None = None

    def __enter__(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        with suppress(OSError):
            os.chmod(self._path, 0o600)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + self._timeout
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise CodexAuthError(
                    "codex 토큰 갱신 잠금 시간이 초과되었습니다. 잠시 후 다시 시도하세요."
                )
            time.sleep(self._poll_interval)
        self._handle = handle
        return True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()


class RefreshGuardState(threading.local):
    """Per-thread recursion depth for one facade's credential mutation guard."""

    def __init__(self) -> None:
        self.depth = 0


@contextmanager
def reentrant_refresh_guard(
    local_lock: AbstractContextManager[bool],
    lock_path: Path,
    state: RefreshGuardState,
    *,
    timeout: float = 45.0,
) -> Iterator[bool]:
    """Combine local and OS locks while allowing same-thread nested mutations."""
    if state.depth:
        state.depth += 1
        try:
            yield True
        finally:
            state.depth -= 1
        return
    with local_lock:
        with InterprocessRefreshLock(lock_path, timeout=timeout):
            state.depth = 1
            try:
                yield True
            finally:
                state.depth = 0


def _try_lock(handle: BinaryIO) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
