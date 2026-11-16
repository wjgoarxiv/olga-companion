"""`/api/proxy` reads and writes the toggle and runs one probe on save.

The sidecar hides the preferences file behind the usual session-token /
same-origin checks that guard every other local route. A save triggers one
probe so the UI never has to guess; the reply carries the probe verdict
(ok, status_code, error_kind, elapsed_ms) verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import sidecar
from olga_companion.agent import session_token
from olga_companion.net import http as net_http
from olga_companion.net import preferences as prefs
from olga_companion.net import proxy_probe


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(prefs, "_file", lambda: tmp_path / "proxy.json")
    net_http.clear_probe_cache()
    with TestClient(sidecar.app) as test_client:
        yield test_client


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def test_the_default_prefs_are_off(client: TestClient) -> None:
    body = client.get("/api/proxy", headers=_headers()).json()
    assert body["enabled"] is False
    assert body["host"] == "127.0.0.1"
    assert body["port"] == 8888
    assert body["probe_target"] == "api.openai.com"
    assert body["last_probe"] is None


def test_missing_session_token_is_refused(client: TestClient) -> None:
    assert client.get("/api/proxy").status_code == 401


def test_save_persists_and_returns_the_probe_result(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        return proxy_probe.ProbeResult(
            ok=True, status_code=200, status_line="HTTP/1.1 200 ok",
            error=None, error_kind=None, elapsed_ms=12,
            proxy=f"{host}:{port}", target=f"{target_host}:{target_port}",
        )

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    payload = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8888,
        "probe_target": "api.openai.com",
        "probe_port": 443,
    }
    response = client.post("/api/proxy", headers=_headers(), json=payload).json()
    assert response["enabled"] is True
    assert response["last_probe"] == {
        "ok": True, "status_code": 200, "error_kind": None,
        "error": None, "elapsed_ms": 12,
    }

    again = client.get("/api/proxy", headers=_headers()).json()
    assert again["enabled"] is True
    assert again["last_probe"]["ok"] is True


def test_save_reports_a_failed_probe_without_hiding_the_reason(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        return proxy_probe.ProbeResult(
            ok=False, status_code=502, status_line="HTTP/1.1 502 Bad Gateway",
            error="HTTP/1.1 502 Bad Gateway", error_kind="http_status", elapsed_ms=6,
            proxy=f"{host}:{port}", target=f"{target_host}:{target_port}",
        )

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    payload = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8888,
        "probe_target": "api.openai.com",
        "probe_port": 443,
    }
    response = client.post("/api/proxy", headers=_headers(), json=payload).json()
    assert response["last_probe"]["ok"] is False
    assert response["last_probe"]["error_kind"] == "http_status"
    assert response["last_probe"]["status_code"] == 502


def test_save_refuses_an_invalid_host(client: TestClient) -> None:
    payload = {
        "enabled": True,
        "host": "https://127.0.0.1",
        "port": 8888,
        "probe_target": "api.openai.com",
        "probe_port": 443,
    }
    response = client.post("/api/proxy", headers=_headers(), json=payload)
    assert response.status_code == 422


def test_save_with_enabled_off_does_not_probe(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple] = []

    async def fake_probe(*args, **kwargs):
        called.append(args)
        raise AssertionError("should not probe when disabled")

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    payload = {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8888,
        "probe_target": "api.openai.com",
        "probe_port": 443,
    }
    body = client.post("/api/proxy", headers=_headers(), json=payload).json()
    assert body["enabled"] is False
    assert body["last_probe"] is None
    assert called == []
