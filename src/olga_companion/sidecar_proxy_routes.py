"""Sidecar routes for the corporate-proxy toggle.

Reads and writes ``~/.olga_copilot/proxy.json`` through the ``net.preferences``
helpers, and runs one probe on save when the toggle is on. Session-token gated
like every other mutating local route; no credentials ever enter requests or
responses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from olga_companion.agent import session_token
from olga_companion.net import http as net_http
from olga_companion.net import preferences, proxy_probe

_HOST_PATTERN = r"^[A-Za-z0-9.-]+$"


def _require_session_token(token: str | None) -> None:
    if not session_token.verify(token):
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")


class ProxyRequest(BaseModel):
    enabled: bool
    host: str = Field(..., pattern=_HOST_PATTERN, max_length=253)
    port: int = Field(..., ge=1, le=65535)
    probe_target: str = Field(..., pattern=_HOST_PATTERN, max_length=253)
    probe_port: int = Field(..., ge=1, le=65535)

    @field_validator("host", "probe_target")
    @classmethod
    def _no_scheme(cls, value: str) -> str:
        if "://" in value or value.startswith(("/", "\\")):
            raise ValueError("must not include a scheme or path")
        return value


router = APIRouter()


@router.get("/api/proxy")
def read(x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    _require_session_token(x_session_token)
    saved = preferences.load()
    return {
        "enabled": saved.enabled,
        "host": saved.host,
        "port": saved.port,
        "probe_target": saved.probe_target,
        "probe_port": saved.probe_port,
        "last_probe": _probe_payload(),
    }


@router.post("/api/proxy")
async def write(payload: ProxyRequest, x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    _require_session_token(x_session_token)
    try:
        new_prefs = preferences.ProxyPrefs(
            enabled=payload.enabled,
            host=payload.host,
            port=payload.port,
            probe_target=payload.probe_target,
            probe_port=payload.probe_port,
        )
        preferences.save(new_prefs)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    net_http.clear_probe_cache()
    probe_result = None
    if new_prefs.enabled:
        probe_result = await proxy_probe.probe(
            new_prefs.host, new_prefs.port,
            new_prefs.probe_target, new_prefs.probe_port,
        )
        net_http.set_probe_result(probe_result)

    return {
        "enabled": new_prefs.enabled,
        "host": new_prefs.host,
        "port": new_prefs.port,
        "probe_target": new_prefs.probe_target,
        "probe_port": new_prefs.probe_port,
        "last_probe": _render(probe_result),
    }


def _probe_payload() -> dict[str, Any] | None:
    cached = net_http._cache  # module-private: last probe for the current prefs
    if cached is None:
        return None
    return _render(cached.result)


def _render(result: proxy_probe.ProbeResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "ok": result.ok,
        "status_code": result.status_code,
        "error_kind": result.error_kind,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
    }
