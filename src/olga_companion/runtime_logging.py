from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response

from .config import project_root

LOGGER_NAME = "olga_companion.runtime_diagnostics"
_MAX_CODE_BODY_BYTES = 4096


def configure_file_logging() -> Path | None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    try:
        path = project_root() / "var" / "logs" / "sidecar.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=1_048_576, backupCount=3, encoding="utf-8"
        )
    except OSError:
        logger.addHandler(logging.NullHandler())
        print("OLGA Companion diagnostic file logging is unavailable.", file=sys.stderr)
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return path


def _conflict_code(body: bytes) -> str | None:
    """Extract only the machine-readable conflict code from a 409 body.

    The body itself (message, paths, keys) is never logged — the code is
    enough to tell the 409 branches apart in the diagnostics bundle.
    """
    if len(body) > _MAX_CODE_BODY_BYTES:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return None
    code = payload.get("code") if isinstance(payload, dict) else None
    if not isinstance(code, str) or not code or len(code) > 128:
        return None
    if any(ord(char) < 32 for char in code):
        return None
    return code


async def _tee_409_code(response: Response) -> tuple[str | None, Response]:
    """Read a small JSON 409 body for its code, then replay it untouched.

    `BaseHTTPMiddleware` hands us a streaming wrapper with no `.body`; the
    consumed bytes are chained back onto the same response object, so the
    wire output is identical with or without a code.
    """
    content_type = response.headers.get("content-type", "")
    iterator = getattr(response, "body_iterator", None)
    if not content_type.startswith("application/json") or iterator is None:
        return None, response
    items: list[Any] = []
    raw = bytearray()
    complete = True
    try:
        async for chunk in iterator:
            items.append(chunk)
            if isinstance(chunk, dict):
                complete = False
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            if not isinstance(chunk, (bytes, bytearray)):
                complete = False
                break
            raw += chunk
            if len(raw) > _MAX_CODE_BODY_BYTES:
                complete = False
                break
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — never break a response
        pass

    async def restore():
        for item in items:
            yield item
        if complete:
            return
        try:
            async for chunk in iterator:
                yield chunk
        except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            return

    response.body_iterator = restore()  # type: ignore[attr-defined]
    if not complete:
        return None, response
    return _conflict_code(bytes(raw)), response


def install_request_diagnostics(app: FastAPI) -> None:
    logger = logging.getLogger(LOGGER_NAME)

    def record(
        request: Request,
        status: int,
        error: Exception | None = None,
        code: str | None = None,
    ):
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        method = request.method if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} else "OTHER"
        kind = type(error).__name__ if error else "HTTP"
        if code is None:
            logger.warning(
                "request_failed method=%s route=%s status=%s kind=%s",
                method, template, status, kind,
            )
        else:
            logger.warning(
                "request_failed method=%s route=%s status=%s kind=%s code=%s",
                method, template, status, kind, code,
            )

    @app.middleware("http")
    async def diagnostics(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as error:
            record(request, 500, error)
            raise
        if response.status_code == 409:
            code, response = await _tee_409_code(response)
            record(request, 409, code=code)
        elif response.status_code >= 400:
            record(request, response.status_code)
        return response
