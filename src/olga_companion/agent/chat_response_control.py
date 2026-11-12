"""Cancellation authority for assistant response orchestration only."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager


_GUARD = threading.Lock()
_ACTIVE: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task[object]]] = {}


@asynccontextmanager
async def active_response(session_id: str) -> AsyncGenerator[None]:
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("Chat response control requires an active asyncio task.")
    loop = asyncio.get_running_loop()
    with _GUARD:
        _ACTIVE[session_id] = (loop, task)
    try:
        yield
    finally:
        with _GUARD:
            current = _ACTIVE.get(session_id)
            if current is not None and current[1] is task:
                _ACTIVE.pop(session_id, None)


def stop_response(session_id: str) -> dict[str, bool | str]:
    with _GUARD:
        active = _ACTIVE.get(session_id)
    if active is None:
        return {"stopped": False, "session_id": session_id}
    loop, task = active
    loop.call_soon_threadsafe(task.cancel)
    return {"stopped": True, "session_id": session_id}
