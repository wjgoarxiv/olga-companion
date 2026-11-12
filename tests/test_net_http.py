"""HTTP factories gate every provider request through one `proxy_url()` seam.

The toggle itself is off by default (task 1 keeps today's behavior byte-for-byte),
so these tests pin both: the factories return plain httpx / aiohttp objects when
`proxy_url()` is None, and inject `proxy=` otherwise. aiohttp takes the proxy
per request, so the subclass has to re-check it on every outbound call.
"""

from __future__ import annotations

import asyncio

import aiohttp
import httpx
import pytest

from olga_companion.net import http as net


def test_proxy_url_is_none_until_the_toggle_is_wired() -> None:
    assert net.proxy_url() is None


def test_httpx_kwargs_add_nothing_when_the_toggle_is_off() -> None:
    assert net._httpx_kwargs({"timeout": 5.0}) == {"timeout": 5.0}


def test_httpx_kwargs_inject_the_proxy_when_the_toggle_is_on(monkeypatch) -> None:
    monkeypatch.setattr(net, "proxy_url", lambda: "http://127.0.0.1:8888")
    assert net._httpx_kwargs({"timeout": 5.0}) == {"timeout": 5.0, "proxy": "http://127.0.0.1:8888"}


def test_an_explicit_proxy_from_the_caller_is_never_overwritten(monkeypatch) -> None:
    monkeypatch.setattr(net, "proxy_url", lambda: "http://127.0.0.1:8888")
    assert net._httpx_kwargs({"proxy": "http://10.0.0.1:3128"}) == {"proxy": "http://10.0.0.1:3128"}


def test_sync_client_returns_an_httpx_client() -> None:
    with net.sync_client(timeout=1.0) as client:
        assert isinstance(client, httpx.Client)


def test_async_client_returns_an_httpx_async_client() -> None:
    client = net.async_client(timeout=1.0)
    assert isinstance(client, httpx.AsyncClient)
    asyncio.run(client.aclose())


def test_aiohttp_session_injects_the_proxy_on_each_request(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(net, "proxy_url", lambda: "http://127.0.0.1:8888")

    async def fake(self, method, url, **kwargs):  # noqa: ARG001
        captured["proxy"] = kwargs.get("proxy")
        raise RuntimeError("stop")

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake)

    async def body() -> None:
        async with net.aiohttp_session() as session:
            with pytest.raises(RuntimeError):
                await session._request("GET", "http://example.com")

    asyncio.run(body())
    assert captured["proxy"] == "http://127.0.0.1:8888"


def test_aiohttp_session_leaves_an_explicit_proxy_alone(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(net, "proxy_url", lambda: "http://127.0.0.1:8888")

    async def fake(self, method, url, **kwargs):  # noqa: ARG001
        captured["proxy"] = kwargs.get("proxy")
        raise RuntimeError("stop")

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake)

    async def body() -> None:
        async with net.aiohttp_session() as session:
            with pytest.raises(RuntimeError):
                await session._request("GET", "http://example.com", proxy="http://10.0.0.1:3128")

    asyncio.run(body())
    assert captured["proxy"] == "http://10.0.0.1:3128"


def test_aiohttp_session_sends_no_proxy_when_the_toggle_is_off(monkeypatch) -> None:
    captured: dict = {"proxy": "untouched"}

    async def fake(self, method, url, **kwargs):  # noqa: ARG001
        captured["proxy"] = kwargs.get("proxy")
        raise RuntimeError("stop")

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake)

    async def body() -> None:
        async with net.aiohttp_session() as session:
            with pytest.raises(RuntimeError):
                await session._request("GET", "http://example.com")

    asyncio.run(body())
    assert captured["proxy"] is None
