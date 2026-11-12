"""Provider, model, and variant survive in app-data config, not beside credentials."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from olga_companion import config, sidecar
from olga_companion.llm import api_key_connections as keys
from olga_companion.llm import factory


def _client() -> tuple[TestClient, str]:
    api = TestClient(sidecar.app)
    token = api.get("/api/session/token").json()["token"]
    return api, token


def test_missing_selection_is_empty_and_requires_the_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olga_companion.llm import factory as llm_factory

    monkeypatch.setattr(llm_factory, "default_connected_selection", lambda: None)
    api, token = _client()

    denied = api.get("/api/llm-selection")
    assert denied.status_code == 401

    body = api.get("/api/llm-selection", headers={"X-Session-Token": token}).json()
    assert body == {"provider": "", "model": "", "variant": ""}
    assert not config.llm_selection_path().exists()


def test_missing_selection_returns_first_connected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olga_companion.llm import factory as llm_factory

    monkeypatch.setattr(
        llm_factory,
        "default_connected_selection",
        lambda: ("apikey", "b" * 32, "medium"),
    )
    api, token = _client()

    body = api.get("/api/llm-selection", headers={"X-Session-Token": token}).json()
    assert body == {"provider": "apikey", "model": "b" * 32, "variant": "medium"}
    assert not config.llm_selection_path().exists()


def test_put_roundtrips_selection_under_var_and_chat_settings_read_it() -> None:
    api, token = _client()
    headers = {"X-Session-Token": token}
    saved = {"provider": "xai", "model": "grok-4.7", "variant": "medium"}

    put = api.put("/api/llm-selection", headers=headers, json=saved)
    assert put.status_code == 200
    assert put.json() == saved

    again = api.get("/api/llm-selection", headers=headers)
    assert again.json() == saved

    path = config.llm_selection_path()
    assert path.name == "llm-selection.json"
    assert path.parent.name == "var"
    assert ".olga_copilot" not in path.parts
    text = path.read_text(encoding="utf-8")
    assert "token" not in text
    assert "grok-4.7" in text

    assert config.llm_selection_settings() == {
        "active_llm_provider": "xai",
        "provider_models": {"xai": "grok-4.7"},
        "active_llm_variant": "medium",
    }

    openai = {"provider": "openai", "model": "gpt-5.6-sol", "variant": "high"}
    assert api.put("/api/llm-selection", headers=headers, json=openai).status_code == 200
    provider, model, variant = factory.resolve_llm_selection(
        {}, config.llm_selection_settings()
    )
    assert (provider, model, variant) == ("openai", "gpt-5.6-sol", "high")


def test_put_rejects_a_secret_field_and_an_unknown_provider() -> None:
    api, token = _client()
    headers = {"X-Session-Token": token}

    path = config.llm_selection_path()
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    extra = api.put(
        "/api/llm-selection",
        headers=headers,
        json={
            "provider": "xai",
            "model": "grok-4.7",
            "variant": "medium",
            "access_token": "secret",
        },
    )
    assert extra.status_code == 400

    unknown = api.put(
        "/api/llm-selection",
        headers=headers,
        json={"provider": "anthropic", "model": "claude", "variant": "medium"},
    )
    assert unknown.status_code == 400
    after = path.read_text(encoding="utf-8") if path.is_file() else None
    assert after == before
    assert "access_token" not in (after or "")


def test_put_keeps_a_verified_apikey_connection_and_rejects_an_unverified_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "llm_selection_path", lambda: tmp_path / "llm-selection.json")
    monkeypatch.setattr(keys, "metadata_path", lambda: tmp_path / "apikey-connections.json")
    monkeypatch.setattr(
        keys,
        "_http_post",
        lambda url, headers, payload, timeout: httpx.Response(200),
    )
    api, token = _client()
    headers = {"X-Session-Token": token}
    saved = api.post(
        "/api/providers/apikey",
        headers=headers,
        json={
            "label": "Mine",
            "protocol": "openai-chat",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "claude-sonnet-5-5",
            "key": "local-test-key",
        },
    ).json()
    assert api.post(
        f"/api/providers/apikey/{saved['id']}/verify", headers=headers
    ).json()["outcome"] == "verified"
    selection = {"provider": "apikey", "model": saved["id"], "variant": "medium"}

    put = api.put("/api/llm-selection", headers=headers, json=selection)

    assert put.status_code == 200
    assert put.json() == selection
    assert api.get("/api/llm-selection", headers=headers).json() == selection
    assert config.load_llm_selection() == selection

    unverified = api.post(
        "/api/providers/apikey",
        headers=headers,
        json={
            "label": "Pending",
            "protocol": "openai-chat",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "claude-sonnet-5-5",
            "key": "local-test-key",
        },
    ).json()
    rejected = api.put(
        "/api/llm-selection",
        headers=headers,
        json={"provider": "apikey", "model": unverified["id"], "variant": "medium"},
    )
    unknown = api.put(
        "/api/llm-selection",
        headers=headers,
        json={"provider": "apikey", "model": "ab" * 16, "variant": "medium"},
    )

    assert rejected.status_code == 400
    assert unknown.status_code == 400
    assert config.load_llm_selection() == selection
