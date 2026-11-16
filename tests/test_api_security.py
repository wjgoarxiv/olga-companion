from __future__ import annotations

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
