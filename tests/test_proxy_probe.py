"""The probe sends a real CONNECT and only accepts a 2xx response.

Mirrors ``bin/Test-SaseProxy.ps1`` in the enterprise-proxy guide: a TCP listener
is not enough evidence, because a stale bridge can accept a socket and still
return 502. The probe therefore opens TCP, writes ``CONNECT host:port HTTP/1.1``,
reads one response line, and classifies each failure so the UI can say why
honestly. No credentials are ever sent.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from olga_companion.net import proxy_probe


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve(port: int, response: bytes, *, reject_after: str | None = None) -> asyncio.base_events.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        first = await reader.readline()
        if reject_after and reject_after not in first.decode("latin-1", "replace"):
            writer.close()
            return
        writer.write(response)
        await writer.drain()
        writer.close()
    return await asyncio.start_server(handle, "127.0.0.1", port)


def test_a_two_hundred_response_reads_as_ok() -> None:
    port = _free_port()

    async def body() -> proxy_probe.ProbeResult:
        server = await _serve(port, b"HTTP/1.1 200 Connection established\r\n\r\n")
        try:
            return await proxy_probe.probe("127.0.0.1", port, "api.openai.com", 443, timeout_s=1.0)
        finally:
            server.close()
            await server.wait_closed()

    result = asyncio.run(body())
    assert result.ok is True
    assert result.status_code == 200
    assert result.error is None


def test_a_five_oh_two_reads_as_http_status(monkeypatch) -> None:
    port = _free_port()

    async def body() -> proxy_probe.ProbeResult:
        server = await _serve(port, b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        try:
            return await proxy_probe.probe("127.0.0.1", port, "api.openai.com", 443, timeout_s=1.0)
        finally:
            server.close()
            await server.wait_closed()

    result = asyncio.run(body())
    assert result.ok is False
    assert result.status_code == 502
    assert result.error_kind == "http_status"


def test_a_closed_port_reads_as_tcp_refused() -> None:
    port = _free_port()

    async def body() -> proxy_probe.ProbeResult:
        return await proxy_probe.probe("127.0.0.1", port, "api.openai.com", 443, timeout_s=1.0)

    result = asyncio.run(body())
    assert result.ok is False
    assert result.error_kind == "tcp_refused"
    assert result.status_code is None


def test_a_server_that_never_answers_times_out() -> None:
    # The TCP connect itself succeeds; the probe then waits for the response line and times out.
    port = _free_port()

    async def body() -> proxy_probe.ProbeResult:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:  # noqa: ARG001
            await asyncio.sleep(5.0)
        server = await asyncio.start_server(handle, "127.0.0.1", port)
        try:
            return await proxy_probe.probe("127.0.0.1", port, "api.openai.com", 443, timeout_s=0.2)
        finally:
            server.close()
            await server.wait_closed()

    result = asyncio.run(body())
    assert result.ok is False
    assert result.error_kind == "response_timeout"


def test_the_probe_sends_no_credentials() -> None:
    port = _free_port()
    seen: list[bytes] = []

    async def body() -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            while True:
                line = await reader.readline()
                if not line or line == b"\r\n":
                    break
                seen.append(line)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(handle, "127.0.0.1", port)
        try:
            await proxy_probe.probe("127.0.0.1", port, "api.openai.com", 443, timeout_s=1.0)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(body())
    blob = b"".join(seen).lower()
    assert b"authorization" not in blob
    assert b"proxy-authorization" not in blob


def test_the_request_line_names_target_and_port() -> None:
    port = _free_port()
    first_lines: list[bytes] = []

    async def body() -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            first_lines.append(await reader.readline())
            writer.write(b"HTTP/1.1 200 ok\r\n\r\n")
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(handle, "127.0.0.1", port)
        try:
            await proxy_probe.probe("127.0.0.1", port, "api.openai.com", 443, timeout_s=1.0)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(body())
    assert first_lines and first_lines[0].startswith(b"CONNECT api.openai.com:443 ")


def test_an_elapsed_ms_is_positive() -> None:
    port = _free_port()

    async def body() -> proxy_probe.ProbeResult:
        return await proxy_probe.probe("127.0.0.1", port, "api.openai.com", 443, timeout_s=0.2)

    result = asyncio.run(body())
    assert result.elapsed_ms >= 0
