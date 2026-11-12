"""Cross-event-loop single-flight leases for Chat sessions."""
from __future__ import annotations

import threading
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

import anyio

_POLL_SECONDS = 0.02
_GUARD = threading.Lock()
_SESSION_LOCKS: dict[str, threading.Lock] = {}


def _session_lock(session_id: str) -> threading.Lock:
    with _GUARD:
        return _SESSION_LOCKS.setdefault(session_id, threading.Lock())


def session_busy(session_id: str) -> bool:
    """True while another turn-like job holds this session."""
    return _session_lock(session_id).locked()


@contextmanager
def session_single_flight_sync(session_id: str) -> Generator[None]:
    """Serialize sync threadpool work against async turns for one session."""
    lock = _session_lock(session_id)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@asynccontextmanager
async def session_single_flight(session_id: str) -> AsyncGenerator[None]:
    """Serialize all turn-like work for one session across event loops."""
    lock = _session_lock(session_id)
    # Polling keeps a cancelled queued turn from acquiring the lock in a worker
    # thread after it was cancelled, which would leave the session held forever.
    while not lock.acquire(blocking=False):
        await anyio.sleep(_POLL_SECONDS)
    try:
        yield
    finally:
        lock.release()
