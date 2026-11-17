"""Bounded localhost callback-server lifecycle for the PKCE login flow."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar, Protocol

from .codex_oauth_models import CodexAuthError


class CallbackHandler(Protocol):
    """Per-flow callback handler state consumed by the server loop."""

    authorization_code: ClassVar[str | None]


class CallbackServer(Protocol):
    """Minimal HTTPServer surface used by the bounded callback loop."""

    timeout: float | None

    def handle_request(self) -> None: ...

    def server_close(self) -> None: ...


def wait_for_authorization_code(
    handler: type[CallbackHandler],
    *,
    port: int,
    timeout: int,
    server_factory: Callable[[tuple[str, int], type[CallbackHandler]], CallbackServer],
    monotonic: Callable[[], float],
    logger: logging.Logger,
) -> str:
    """Wait through stray requests until a valid callback or deadline."""
    try:
        server = server_factory(("localhost", port), handler)
    except OSError as exc:
        logger.warning(
            "codex self-OAuth: cannot bind callback port %s: %s",
            port,
            type(exc).__name__,
        )
        raise CodexAuthError(
            f"콜백 포트 {port} 사용 불가: {type(exc).__name__}"
        ) from None
    logger.info(
        "codex self-OAuth: callback server listening on localhost:%s — waiting for sign-in",
        port,
    )
    server.timeout = min(5, timeout)
    deadline = monotonic() + timeout
    try:
        while handler.authorization_code is None and monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    auth_code = handler.authorization_code
    if not auth_code:
        logger.warning(
            "codex self-OAuth: no callback within %ss (browser not opened, blocked, or sign-in not completed)",
            timeout,
        )
        raise CodexAuthError("codex 로그인이 취소되었거나 시간 초과되었습니다.")
    return auth_code
