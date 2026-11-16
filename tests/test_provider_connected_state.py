"""Provider connected-state contract (musedev frontend lane dependency).

GET /api/providers lists only backends with a truthful local `connected`
flag + `login` kind; an empty saved selection resolves to the first
connected provider; the chat not-connected error speaks Korean.
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from olga_companion.agent import chat, history
from olga_companion.llm import (
    api_key_connections as keys,
    catalog,
    factory,
)
from olga_companion.llm.antigravity import token as ag_token
from olga_companion.llm import codex_oauth, copilot_auth, xai_oauth
from olga_companion.sidecar import app

client = TestClient(app)

PROVIDER_ORDER = ["openai", "copilot", "antigravity", "xai", "apikey"]
FAKE_CONN_ID = "a" * 32


def _all_disconnected(monkeypatch) -> None:
    monkeypatch.setattr(codex_oauth, "load_credentials", lambda: None)
    monkeypatch.setattr(copilot_auth, "load_tokens", lambda: None)
    monkeypatch.setattr(ag_token, "load_tokens", lambda: None)
    monkeypatch.setattr(xai_oauth, "login_status", lambda: {"state": "idle"})
    monkeypatch.setattr(keys, "catalog_entries", lambda: [])


def test_providers_lists_only_backends_in_order_with_login() -> None:
    body = client.get("/api/providers").json()["providers"]
    assert [p["provider"] for p in body] == PROVIDER_ORDER
    assert {p["provider"] for p in body} == set(PROVIDER_ORDER)
    by_name = {p["provider"]: p for p in body}
    assert by_name["xai"]["login"] == "xai_device"
    assert by_name["apikey"]["login"] == "apikey"
    for name in ("openai", "copilot", "antigravity"):
        assert by_name[name]["login"] == "external"
    for item in body:
        assert set(item) >= {"provider", "known", "models", "has_catalog", "connected", "login"}


def test_connected_true_when_loaders_report_login(monkeypatch) -> None:
    monkeypatch.setattr(codex_oauth, "load_credentials", lambda: object())
    monkeypatch.setattr(copilot_auth, "load_tokens", lambda: {"github_token": "x"})
    monkeypatch.setattr(ag_token, "load_tokens", lambda: object())
    monkeypatch.setattr(xai_oauth, "login_status", lambda: {"state": "connected"})
    monkeypatch.setattr(
        keys, "catalog_entries", lambda: [{"id": FAKE_CONN_ID, "label": "T"}]
    )
    by_name = {p["provider"]: p for p in client.get("/api/providers").json()["providers"]}
    assert all(by_name[name]["connected"] is True for name in PROVIDER_ORDER)


def test_connected_false_when_loaders_report_logout(monkeypatch) -> None:
    _all_disconnected(monkeypatch)
    by_name = {p["provider"]: p for p in client.get("/api/providers").json()["providers"]}
    assert all(by_name[name]["connected"] is False for name in PROVIDER_ORDER)


def test_connected_false_when_loaders_raise(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("disk hiccup")

    monkeypatch.setattr(codex_oauth, "load_credentials", _boom)
    monkeypatch.setattr(copilot_auth, "load_tokens", _boom)
    monkeypatch.setattr(ag_token, "load_tokens", _boom)
    monkeypatch.setattr(xai_oauth, "login_status", _boom)
    monkeypatch.setattr(keys, "catalog_entries", _boom)
    response = client.get("/api/providers")
    assert response.status_code == 200
    by_name = {p["provider"]: p for p in response.json()["providers"]}
    assert all(by_name[name]["connected"] is False for name in PROVIDER_ORDER)


def test_default_pick_is_apikey_when_only_apikey_connected(monkeypatch) -> None:
    _all_disconnected(monkeypatch)
    monkeypatch.setattr(
        keys, "catalog_entries", lambda: [{"id": FAKE_CONN_ID, "label": "T"}]
    )
    provider, model, _variant = factory.resolve_llm_selection({}, {})
    assert provider == "apikey"
    assert model == FAKE_CONN_ID


def test_saved_selection_is_kept_even_when_disconnected(monkeypatch) -> None:
    _all_disconnected(monkeypatch)
    provider, model, _variant = factory.resolve_llm_selection(
        {}, {"active_llm_provider": "copilot", "provider_models": {}, "active_llm_variant": "medium"}
    )
    assert provider == "copilot"


def test_chat_not_connected_error_is_korean() -> None:
    session_id = history.new_session("disconnected chat")
    chat.set_client_builder(lambda _p, _m, _v: None)
    try:
        collected = []

        async def _drain():
            async for event in chat.run_chat_turn(
                session_id, "hi", provider="antigravity", model="m", variant="medium"
            ):
                collected.append(event)

        asyncio.run(_drain())
    finally:
        chat.set_client_builder(None)
    assert collected and collected[0].type == "error"
    message = collected[0].data["message"]
    assert message == (
        "선택한 AI 공급자(Antigravity (Gemini))가 연결되어 있지 않습니다. "
        "설정 → AI 공급자에서 연결된 공급자를 고르세요."
    )


def test_catalog_knows_only_backends() -> None:
    assert catalog.is_known_provider("openai")
    assert catalog.is_known_provider("apikey")
    assert not catalog.is_known_provider("anthropic")
    assert not catalog.is_known_provider("openrouter")
