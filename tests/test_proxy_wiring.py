"""`proxy_url()` reads prefs and the last probe result, nothing else at request time.

Probing on every outbound request would multiply latency; probing never would
leave a dead proxy on. The seam therefore caches the last probe result and
re-runs the probe only on explicit refresh (startup and the settings panel).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from olga_companion.net import http as net_http
from olga_companion.net import preferences as prefs
from olga_companion.net import proxy_probe


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prefs, "_file", lambda: tmp_path / "proxy.json")
    net_http.clear_probe_cache()


def test_proxy_url_is_none_when_prefs_disabled(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    assert net_http.proxy_url() is None


def test_proxy_url_returns_the_url_when_enabled_and_probe_ok(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target="api.openai.com", probe_port=443))
    net_http.set_probe_result(_ok_result())
    assert net_http.proxy_url() == "http://127.0.0.1:8888"


def test_proxy_url_is_none_when_probe_failed(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target="api.openai.com", probe_port=443))
    net_http.set_probe_result(_fail_result("http_status", 502))
    assert net_http.proxy_url() is None


def test_proxy_url_is_none_when_no_probe_has_run(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target="api.openai.com", probe_port=443))
    assert net_http.proxy_url() is None


def test_changing_prefs_invalidates_the_cached_probe(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target="api.openai.com", probe_port=443))
    net_http.set_probe_result(_ok_result())
    assert net_http.proxy_url() == "http://127.0.0.1:8888"

    prefs.save(prefs.ProxyPrefs(enabled=True, host="10.0.0.1", port=3128,
                                probe_target="api.openai.com", probe_port=443))
    assert net_http.proxy_url() is None


def test_refresh_runs_a_probe_and_caches_it(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target="api.openai.com", probe_port=443))

    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        return _ok_result(host=host, port=port, target=target_host, target_port=target_port)

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    result = asyncio.run(net_http.refresh())
    assert result.ok is True
    assert net_http.proxy_url() == "http://127.0.0.1:8888"


def test_refresh_does_not_probe_when_disabled(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    calls: list[tuple] = []

    async def fake_probe(*args, **kwargs):
        calls.append(args)
        return _ok_result()

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    result = asyncio.run(net_http.refresh())
    assert result is None
    assert calls == []


def _ok_result(*, host: str = "127.0.0.1", port: int = 8888,
               target: str = "api.openai.com", target_port: int = 443) -> proxy_probe.ProbeResult:
    return proxy_probe.ProbeResult(
        ok=True, status_code=200, status_line="HTTP/1.1 200 ok",
        error=None, error_kind=None, elapsed_ms=12,
        proxy=f"{host}:{port}", target=f"{target}:{target_port}",
    )


def _fail_result(kind: str, code: int | None) -> proxy_probe.ProbeResult:
    return proxy_probe.ProbeResult(
        ok=False, status_code=code,
        status_line="HTTP/1.1 502 Bad Gateway" if code else None,
        error="probe failed", error_kind=kind, elapsed_ms=7,
        proxy="127.0.0.1:8888", target="api.openai.com:443",
    )
