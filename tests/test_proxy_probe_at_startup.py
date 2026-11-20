"""The saved proxy is used right after the app starts, not only after Settings is saved.

Bug report 2026-11-15 (0.1.8, company PC): the proxy toggle was on, but after a
restart every chat failed with "Cannot connect to host api.x.ai:443 [access denied]".
`proxy_url()` only routes through the proxy after a successful probe, and the probe
ran only when the Settings panel saved, so each new sidecar went direct.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from olga_companion.net import http as net_http
from olga_companion.net import preferences as prefs
from olga_companion.net import proxy_probe


def _result(ok: bool) -> proxy_probe.ProbeResult:
    return proxy_probe.ProbeResult(
        ok=ok, status_code=200 if ok else None, status_line=None,
        error=None if ok else "connection refused", error_kind=None if ok else "tcp_refused",
        elapsed_ms=1, proxy="127.0.0.1:8888", target="api.openai.com:443",
    )


def _enable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prefs, "_file", lambda: tmp_path / "proxy.json")
    net_http.clear_probe_cache()
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target="api.openai.com", probe_port=443))


def test_a_started_sidecar_routes_through_the_saved_proxy(tmp_path: Path, monkeypatch) -> None:
    _enable(tmp_path, monkeypatch)

    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        return _result(True)

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    from olga_companion import sidecar

    with TestClient(sidecar.app):
        deadline = time.monotonic() + 5
        while net_http.proxy_url() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert net_http.proxy_url() == "http://127.0.0.1:8888"
    net_http.clear_probe_cache()


def test_a_proxy_that_was_not_up_yet_is_probed_again(tmp_path: Path, monkeypatch) -> None:
    _enable(tmp_path, monkeypatch)
    answers = iter([False, True])

    async def fake_probe(host, port, target_host, target_port, *, timeout_s=2.0):
        return _result(next(answers))

    monkeypatch.setattr(proxy_probe, "probe", fake_probe)
    seen: list[str | None] = []

    async def fake_sleep(_seconds: float) -> None:
        seen.append(net_http.proxy_url())
        if len(seen) == 2:
            raise asyncio.CancelledError

    try:
        asyncio.run(net_http.keep_probed(sleep=fake_sleep))
    except asyncio.CancelledError:
        pass

    assert seen == [None, "http://127.0.0.1:8888"]
    net_http.clear_probe_cache()
