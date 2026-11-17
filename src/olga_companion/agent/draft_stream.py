"""Live draft side channel: redacted answer deltas drained while the provider streams."""
from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import AsyncIterator
from typing import Any

# The end of a buffer that could still grow into a secret: a trailing token-character run,
# or "Bearer" with its whitespace and a possibly empty, still-open token.
_OPEN_TAIL = re.compile(r"(?:Bearer\s+\S*|[A-Za-z0-9_\-]*)\Z", re.IGNORECASE)
# Only the end of the buffer can still grow into a secret; searching further back is
# quadratic on a long token run, and a held-back tail must stay small.
_TAIL_WINDOW = 256
_CANCEL_GRACE_SECONDS = 1.0


def _accepts_on_token(stream_generate: Any) -> bool:
    """A client written before `on_token` joined the protocol streams no draft rather than fail."""
    try:
        parameters = inspect.signature(stream_generate).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        item.name == "on_token" or item.kind is inspect.Parameter.VAR_KEYWORD
        for item in parameters
    )


class DraftRedactor:
    """Redacts secrets in streamed deltas, holding back a tail a later delta may complete."""

    def __init__(self, secret: re.Pattern[str]) -> None:
        self._secret = secret
        self._carry = ""

    def feed(self, delta: str) -> str:
        buffer = self._carry + delta
        match = _OPEN_TAIL.search(buffer, max(0, len(buffer) - _TAIL_WINDOW))
        cut = len(buffer) if match is None else match.start()
        self._carry = buffer[cut:]
        return self._secret.sub("<redacted>", buffer[:cut])

    def flush(self) -> str:
        carry, self._carry = self._carry, ""
        return self._secret.sub("<redacted>", carry)


async def drafting_generation(
    client: Any, kwargs: dict[str, Any], secret: re.Pattern[str]
) -> AsyncIterator[str | Any]:
    """Run `stream_generate`, yielding redacted draft text as it arrives, then the result.

    Draft text is yielded as `str`; the single non-str item is the provider result. The
    provider call is cancelled with this generator, so a stopped turn leaves no stream behind.
    """
    queue: asyncio.Queue[str] = asyncio.Queue()
    redactor = DraftRedactor(secret)

    async def on_token(delta: str) -> None:
        safe = redactor.feed(delta)
        if safe:
            queue.put_nowait(safe)

    def drain(first: str = "") -> str:
        pieces = [first] if first else []
        while not queue.empty():
            pieces.append(queue.get_nowait())
        return "".join(pieces)

    if _accepts_on_token(client.stream_generate):
        kwargs = {**kwargs, "on_token": on_token}
    task = asyncio.ensure_future(client.stream_generate(**kwargs))
    getter: asyncio.Future[str] | None = None
    try:
        while not task.done():
            getter = asyncio.ensure_future(queue.get())
            await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter.done() and not getter.cancelled():
                text = drain(getter.result())
                if text:
                    yield text
            else:
                getter.cancel()
        text = drain() + redactor.flush()
        if text:
            yield text
        yield task.result()
    finally:
        if getter is not None and not getter.done():
            getter.cancel()
        if not task.done():
            task.cancel()
            # Let the provider unwind its stream before this generator closes.
            await asyncio.wait({task}, timeout=_CANCEL_GRACE_SECONDS)
        if task.done() and not task.cancelled():
            task.exception()
