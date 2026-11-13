from __future__ import annotations

import ipaddress
import os
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import FRONTEND_PORT, SIDECAR_PORT

PACKAGED_WEBVIEW_ORIGINS = (
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)


def _facade() -> Any:
    from . import sidecar

    return sidecar


@asynccontextmanager
async def lifespan(_: FastAPI):
    sidecar = _facade()
    try:
        yield
    finally:
        try:
            sidecar.native_dialogs.cancel_all()
        finally:
            sidecar.shutdown_direct_runs()


def is_loopback_host(value: str) -> bool:
    host = value.strip().rstrip(".").casefold()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def runtime_port(name: str, default: int) -> int:
    try:
        port = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


def host_header_is_allowed(authority: str, request: Request) -> bool:
    if (
        request.client
        and request.client.host == "testclient"
        and authority.casefold() == "testserver"
    ):
        return True
    if not authority or "@" in authority or any(ord(char) < 33 for char in authority):
        return False
    try:
        hostname = urlsplit(f"//{authority}").hostname
    except ValueError:
        return False
    return bool(hostname and is_loopback_host(hostname))


def origin_is_allowed(origin: str) -> bool:
    if origin in PACKAGED_WEBVIEW_ORIGINS:
        return True
    try:
        parsed = urlsplit(origin)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme == "tauri" and hostname == "localhost" and port is None:
        return True
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or not is_loopback_host(hostname)
    ):
        return False
    return port in {
        runtime_port("OLGA_FRONTEND_PORT", FRONTEND_PORT),
        runtime_port("OLGA_SIDECAR_PORT", SIDECAR_PORT),
    }


def test_transport(request: Request) -> bool:
    return bool(
        request.client
        and request.client.host == "testclient"
        and request.headers.get("host", "").casefold() == "testserver"
    )


async def local_api_guard(request: Request, call_next):
    """Keep the privileged sidecar local, same-origin, and boot-token scoped."""
    if not host_header_is_allowed(request.headers.get("host", ""), request):
        return JSONResponse(
            status_code=400, content={"detail": "Untrusted Host header."}
        )
    origin = request.headers.get("origin")
    if origin and not origin_is_allowed(origin):
        return JSONResponse(
            status_code=403, content={"detail": "Origin is not allowed."}
        )
    sidecar = _facade()
    if (
        request.url.path.startswith("/api/")
        and request.url.path != "/api/session/token"
        and not test_transport(request)
        and not sidecar.session_token.verify(request.headers.get("x-session-token"))
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid session token."},
        )
    response = await call_next(request)
    if request.url.path == "/api/session/token":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


def install_local_api_guard(app: FastAPI) -> None:
    app.middleware("http")(local_api_guard)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(PACKAGED_WEBVIEW_ORIGINS),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-Session-Token",
            "x-llm-provider",
            "x-llm-model",
            "x-llm-variant",
        ],
        allow_credentials=False,
        max_age=3600,
    )
