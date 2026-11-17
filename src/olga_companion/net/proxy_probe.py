"""CONNECT-based proxy probe, mirroring the enterprise-proxy guide's helper.

A listening socket is not evidence: a stale bridge accepts a connection and
still answers 502. The probe therefore sends one HTTP CONNECT request and
classifies the outcome so the UI can tell the user *why* the proxy is unusable.
No credentials, no body, no retries — one short exchange and a verdict.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    status_code: int | None
    status_line: str | None
    error: str | None
    error_kind: str | None
    elapsed_ms: int
    proxy: str
    target: str


def _finalize(start: float, *, proxy: str, target: str, ok: bool,
              status_code: int | None = None, status_line: str | None = None,
              error: str | None = None, error_kind: str | None = None) -> ProbeResult:
    return ProbeResult(
        ok=ok, status_code=status_code, status_line=status_line,
        error=error, error_kind=error_kind,
        elapsed_ms=max(0, int((time.monotonic() - start) * 1000)),
        proxy=proxy, target=target,
    )


async def probe(host: str, port: int, target_host: str, target_port: int,
                *, timeout_s: float = 2.0) -> ProbeResult:
    start = time.monotonic()
    proxy = f"{host}:{port}"
    target = f"{target_host}:{target_port}"
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        return _finalize(start, proxy=proxy, target=target, ok=False,
                         error="connect timed out", error_kind="connect_timeout")
    except ConnectionRefusedError:
        return _finalize(start, proxy=proxy, target=target, ok=False,
                         error="connection refused", error_kind="tcp_refused")
    except OSError as exc:
        return _finalize(start, proxy=proxy, target=target, ok=False,
                         error=str(exc), error_kind="io")

    try:
        request = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {target_host}:{target_port}\r\n"
            f"User-Agent: olga-companion-probe/1\r\n"
            f"Proxy-Connection: close\r\n"
            f"\r\n"
        ).encode("ascii")
        writer.write(request)
        try:
            await asyncio.wait_for(writer.drain(), timeout=timeout_s)
            line = await asyncio.wait_for(reader.readline(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return _finalize(start, proxy=proxy, target=target, ok=False,
                             error="no response from proxy", error_kind="response_timeout")

        decoded = line.decode("latin-1", "replace").rstrip("\r\n")
        if not decoded:
            return _finalize(start, proxy=proxy, target=target, ok=False,
                             error="empty response", error_kind="empty_response")

        parts = decoded.split(" ", 2)
        try:
            code = int(parts[1])
        except (IndexError, ValueError):
            return _finalize(start, proxy=proxy, target=target, ok=False,
                             error=f"malformed status line: {decoded!r}",
                             error_kind="malformed")

        if 200 <= code < 300:
            return _finalize(start, proxy=proxy, target=target, ok=True,
                             status_code=code, status_line=decoded)
        return _finalize(start, proxy=proxy, target=target, ok=False,
                         status_code=code, status_line=decoded,
                         error=decoded, error_kind="http_status")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, RuntimeError):
            pass
