"""The default proxy probe accepts any known AI provider host.

Owner report 2026-11-16 (0.1.9, company PC): chat still failed. The company proxy
refused CONNECT to the default probe target api.openai.com, so the probe never
passed and chat went direct and was blocked. Setting the target to api.x.ai made
chat work. With the default target the probe now tries the provider hosts in turn.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from olga_companion.net import http as net_http
from olga_companion.net import preferences as prefs
from olga_companion.net import proxy_probe


def _result(target: str, *, ok: bool, kind: str | None = None) -> proxy_probe.ProbeResult:
    return proxy_probe.ProbeResult(
        ok=ok, status_code=200 if ok else (403 if kind == "http_status" else None),
        status_line=None, error=None if ok else kind, error_kind=None if ok else kind,
        elapsed_ms=1, proxy="127.0.0.1:8888", target=f"{target}:443",
    )


def _save(tmp_path: Path, monkeypatch, target: str) -> None:
    monkeypatch.setattr(prefs, "_file", lambda: tmp_path / "proxy.json")
    net_http.clear_probe_cache()
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target=target, probe_port=443))


def test_default_target_passes_through_another_provider_host(tmp_path: Path, monkeypatch) -> None:
    _save(tmp_path, monkeypatch, "api.openai.com")
    tried: list[str] = []

    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        tried.append(target_host)
        return _result(target_host, ok=target_host == "api.x.ai", kind="http_status")

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    result = asyncio.run(net_http.refresh())
    assert result is not None and result.ok
    assert tried[0] == "api.openai.com" and "api.x.ai" in tried
    assert net_http.proxy_url() == "http://127.0.0.1:8888"
    net_http.clear_probe_cache()


def test_a_dead_proxy_is_probed_once(tmp_path: Path, monkeypatch) -> None:
    _save(tmp_path, monkeypatch, "api.openai.com")
    tried: list[str] = []

    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        tried.append(target_host)
        return _result(target_host, ok=False, kind="tcp_refused")

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    result = asyncio.run(net_http.refresh())
    assert result is not None and not result.ok
    assert tried == ["api.openai.com"]
    assert net_http.proxy_url() is None
    net_http.clear_probe_cache()


def test_a_typed_target_is_probed_alone(tmp_path: Path, monkeypatch) -> None:
    _save(tmp_path, monkeypatch, "gateway.example.test")
    tried: list[str] = []

    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        tried.append(target_host)
        return _result(target_host, ok=False, kind="http_status")

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    asyncio.run(net_http.refresh())
    assert tried == ["gateway.example.test"]
    net_http.clear_probe_cache()


def test_saving_settings_uses_the_same_probe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prefs, "_file", lambda: tmp_path / "proxy.json")
    net_http.clear_probe_cache()

    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        return _result(target_host, ok=target_host == "api.x.ai", kind="http_status")

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    from olga_companion import sidecar

    from olga_companion.agent import session_token

    with TestClient(sidecar.app) as client:
        response = client.post("/api/proxy", headers={"X-Session-Token": session_token.boot_token()}, json={
            "enabled": True, "host": "127.0.0.1", "port": 8888,
            "probe_target": "api.openai.com", "probe_port": 443,
        })
    assert response.status_code == 200
    assert response.json()["last_probe"]["ok"] is True
    net_http.clear_probe_cache()
