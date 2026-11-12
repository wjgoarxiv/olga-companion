from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request

from .config import project_root

LOGGER_NAME = "olga_companion.runtime_diagnostics"


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


def install_request_diagnostics(app: FastAPI) -> None:
    logger = logging.getLogger(LOGGER_NAME)

    def record(request: Request, status: int, error: Exception | None = None):
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        method = request.method if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} else "OTHER"
        logger.warning(
            "request_failed method=%s route=%s status=%s kind=%s",
            method, template, status, type(error).__name__ if error else "HTTP",
        )

    @app.middleware("http")
    async def diagnostics(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as error:
            record(request, 500, error)
            raise
        if response.status_code >= 400:
            record(request, response.status_code)
        return response
