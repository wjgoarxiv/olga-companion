"""Session-token protected xAI provider routes."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from olga_companion.agent import session_token
from olga_companion.llm import xai_oauth
from olga_companion.sidecar import app

ROUTES = (
    ("post", "/api/providers/xai/login"),
    ("get", "/api/providers/xai/login/status"),
    ("post", "/api/providers/xai/logout"),
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(xai_oauth, "TOKENS_FILE", tmp_path / "xai_tokens.json")
    xai_oauth._reset_for_tests()
    yield TestClient(app)
    xai_oauth._reset_for_tests()


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_routes_reject_missing_or_wrong_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"X-Session-Token": "nope"}).status_code == 401


def test_login_status_logout_flow(client, monkeypatch):
    headers = {"X-Session-Token": session_token.boot_token()}
    monkeypatch.setattr(
        xai_oauth,
        "start_login",
        lambda: {
            "user_code": "ABCD-1234",
            "verification_uri": "https://accounts.x.ai/device",
            "verification_uri_complete": "https://accounts.x.ai/device?user_code=ABCD-1234",
            "expires_at": 123.0,
        },
    )
    r = client.post("/api/providers/xai/login", headers=headers)
    assert r.status_code == 200 and r.json()["user_code"] == "ABCD-1234"

    r = client.get("/api/providers/xai/login/status", headers=headers)
    assert r.status_code == 200 and r.json()["state"] == "idle"
    assert "token" not in json.dumps(r.json()).lower()

    r = client.post("/api/providers/xai/logout", headers=headers)
    assert r.status_code == 200 and r.json()["state"] == "idle"


def test_login_failure_is_a_korean_502_without_secrets(client, monkeypatch):
    def fail():
        raise xai_oauth.XaiAuthError("xAI 로그인을 시작하지 못했습니다.")

    monkeypatch.setattr(xai_oauth, "start_login", fail)
    r = client.post("/api/providers/xai/login", headers={"X-Session-Token": session_token.boot_token()})
    assert r.status_code == 502 and "xAI" in r.json()["detail"]


def test_providers_lists_xai(client):
    names = [p["provider"] for p in client.get("/api/providers").json()["providers"]]
    assert "xai" in names
