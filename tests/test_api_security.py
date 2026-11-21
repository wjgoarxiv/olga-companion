from __future__ import annotations

import os

from fastapi.testclient import TestClient
import pytest

from olga_companion.agent import session_token
from olga_companion.sidecar import _is_loopback_host, _origin_is_allowed, app


def _network_client() -> TestClient:
    return TestClient(
        app,
        base_url="http://127.0.0.1:8865",
        client=("127.0.0.1", 50000),
    )


def test_local_api_rejects_untrusted_host_header() -> None:
    response = _network_client().get("/health", headers={"Host": "attacker.example"})

    assert response.status_code == 400


def test_local_api_rejects_cross_origin_token_bootstrap() -> None:
    response = _network_client().get(
        "/api/session/token", headers={"Origin": "https://attacker.example"}
    )

    assert response.status_code == 403


def test_packaged_tauri_origin_is_allowed_and_receives_cors_headers() -> None:
    origin = "http://tauri.localhost"

    assert _origin_is_allowed(origin) is True
    response = _network_client().get(
        "/api/session/token", headers={"Origin": origin}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_packaged_tauri_preflight_allows_only_required_session_header() -> None:
    origin = "http://tauri.localhost"
    response = _network_client().options(
        "/api/providers",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Session-Token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "x-session-token" in response.headers[
        "access-control-allow-headers"
    ].casefold()


def test_packaged_tauri_preflight_allows_chat_provider_selection_headers() -> None:
    # streamChat sends the provider choice as x-llm-* headers; a blocked preflight
    # surfaces in the packaged app as "Local runtime is offline".
    origin = "http://tauri.localhost"
    response = _network_client().options(
        "/api/chat",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "content-type,x-session-token,x-llm-provider,x-llm-model,x-llm-variant"
            ),
        },
    )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].casefold()
    for header in ("x-llm-provider", "x-llm-model", "x-llm-variant"):
        assert header in allowed


def test_packaged_tauri_preflight_rejects_unlisted_headers() -> None:
    response = _network_client().options(
        "/api/chat",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-forwarded-host",
        },
    )

    assert response.status_code == 400


def test_token_bootstrap_is_never_cacheable() -> None:
    response = _network_client().get("/api/session/token")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


@pytest.mark.parametrize("host", ["127.0.0.1", "127.17.0.9", "::1", "localhost", "LOCALHOST."])
def test_sidecar_bind_accepts_loopback_hosts(host: str) -> None:
    assert _is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.4", "example.com", "localhost.evil"])
def test_sidecar_bind_rejects_non_loopback_hosts(host: str) -> None:
    assert _is_loopback_host(host) is False


def test_all_non_bootstrap_api_routes_require_the_boot_token() -> None:
    client = _network_client()

    assert client.get("/api/providers").status_code == 401
    assert client.post(
        "/api/genkey/create",
        json={"topology": "simple_pipeline", "endtime_s": 3600, "pvtfile": "./fluid.tab"},
    ).status_code == 401
    assert client.get(
        "/api/providers", headers={"X-Session-Token": "forged"}
    ).status_code == 401

    response = client.get(
        "/api/providers",
        headers={
            "Origin": "http://127.0.0.1:5273",
            "X-Session-Token": session_token.boot_token(),
        },
    )
    assert response.status_code == 200


def test_run_api_rejects_unbounded_timeout_at_schema_boundary() -> None:
    response = _network_client().post(
        "/api/run/preview",
        json={"source": "case.genkey", "timeout_s": 604_801},
        headers={"X-Session-Token": session_token.boot_token()},
    )

    assert response.status_code == 422


def _dev_origin_request() -> int:
    return _network_client().get(
        "/api/providers",
        headers={
            "Origin": "http://127.0.0.1:5273",
            "X-Session-Token": session_token.boot_token(),
        },
    ).status_code


def test_a_release_build_does_not_trust_the_dev_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.1.20 row 12: the packaged app never serves the Vite dev page, so port 5273 is not trusted."""
    from olga_companion import sidecar_local_api

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(sidecar_local_api, "_dev_frontend_trusted", None)
    assert _origin_is_allowed("http://127.0.0.1:5273") is False
    assert _origin_is_allowed("http://localhost:5273") is False
    assert _dev_origin_request() == 403
    # The packaged webview origins are unchanged.
    assert _origin_is_allowed("http://tauri.localhost") is True
    assert _origin_is_allowed("tauri://localhost") is True


def test_a_debug_shell_that_names_the_dev_port_keeps_it_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion import sidecar_local_api

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(sidecar_local_api, "_dev_frontend_trusted", True)
    assert _origin_is_allowed("http://127.0.0.1:5273") is True
    assert _dev_origin_request() == 200


def test_the_sidecar_trusts_the_dev_port_only_when_told_or_unpackaged(monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion import sidecar_local_api
    from olga_companion.sidecar import dev_frontend_trusted

    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert dev_frontend_trusted(None) is False
    assert dev_frontend_trusted(5273) is True
    monkeypatch.delattr("sys.frozen")
    assert dev_frontend_trusted(None) is True
    assert sidecar_local_api is not None


def test_a_packaged_backend_does_not_serve_its_session_token_over_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.1.20 review: any local program (a connected AI tool's shell) could fetch it and click approvals."""
    from olga_companion import sidecar_local_api

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(sidecar_local_api, "_dev_frontend_trusted", None)
    assert _network_client().get("/api/session/token").status_code == 404
    monkeypatch.setattr(sidecar_local_api, "_dev_frontend_trusted", True)
    assert _network_client().get("/api/session/token").json()["token"] == session_token.boot_token()


def test_the_backend_announces_its_token_once_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    from olga_companion.sidecar import announce_session_token

    announce_session_token()
    assert capsys.readouterr().out == f"OLGA_SESSION_TOKEN={session_token.boot_token()}\n"


def test_the_token_is_announced_only_once_the_port_is_ours(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """0.1.20 review: a sidecar that cannot bind (an orphan holds the port) must not hand the
    shell a token for a server that never starts."""
    import socket

    from olga_companion import sidecar

    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    from olga_companion import sidecar_local_api

    # main() sets these for the process; register them so they are put back after the test.
    for name in ("OLGA_SIDECAR_PORT", "OLGA_FRONTEND_PORT"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        if not os.environ[name]:
            monkeypatch.delenv(name)
    monkeypatch.setattr(sidecar_local_api, "_dev_frontend_trusted", sidecar_local_api._dev_frontend_trusted)
    monkeypatch.setattr(sidecar, "start_parent_watch", lambda _gone: None)
    monkeypatch.setattr(sidecar, "configure_file_logging", lambda: None)
    monkeypatch.setattr("sys.argv", ["olga-companion-sidecar", "--port", str(port)])
    try:
        with pytest.raises(SystemExit):
            sidecar.main()
    finally:
        holder.close()
    assert "OLGA_SESSION_TOKEN=" not in capsys.readouterr().out
