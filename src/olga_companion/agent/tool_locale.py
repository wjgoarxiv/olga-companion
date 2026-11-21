"""The UI language of the chat turn a tool call runs in, for tool text the user may read.

The runtime sets it around each dispatch; a tool called outside a turn sees None.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_LOCALE: ContextVar[str | None] = ContextVar("tool_locale", default=None)


def current() -> str | None:
    """"en" or "ko" inside a chat turn, else None."""
    return _LOCALE.get()


@contextmanager
def using(locale: str | None) -> Iterator[None]:
    token = _LOCALE.set(locale if locale in ("en", "ko") else None)
    try:
        yield
    finally:
        _LOCALE.reset(token)
