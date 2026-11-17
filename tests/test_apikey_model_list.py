"""An API-key connection can list the server's chat models before it is saved (HD AIC needs this)."""

from __future__ import annotations

import pytest

from olga_companion.llm import api_key_connections as keys


def _serve(monkeypatch: pytest.MonkeyPatch, status: int, body: object) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def fake(url: str, headers: dict, timeout: float):
        calls.append((url, headers))
        return status, body

    monkeypatch.setattr(keys, "_http_get_json", fake)
    return calls


def test_text_models_are_listed_sorted_and_media_models_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, 200, {"data": [{"id": "qwen3-8-27b"}, {"id": "gpt-image-1"}, {"id": "a-model"}, {"id": "text-embedding-3"}, {"id": "qwen3-8-27b"}]})

    result = keys.list_models({"base_url": "https://api.model.hd-aic.com/v1", "key": "sk-test"})

    assert result == {"outcome": "listed", "models": ["a-model", "qwen3-8-27b"]}
    assert calls[0][0] == "https://api.model.hd-aic.com/v1/models"
    assert calls[0][1]["Authorization"] == "Bearer sk-test"


@pytest.mark.parametrize(("status", "outcome"), [(401, "unauthorized"), (404, "not_found"), (500, "unexpected_response")])
def test_a_refused_list_names_why(monkeypatch: pytest.MonkeyPatch, status: int, outcome: str) -> None:
    _serve(monkeypatch, status, None)
    assert keys.list_models({"base_url": "https://x.example/v1", "key": "k"}) == {"outcome": outcome, "models": []}


def test_an_unreachable_server_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, headers: dict, timeout: float):
        raise OSError("no route")

    monkeypatch.setattr(keys, "_http_get_json", boom)
    assert keys.list_models({"base_url": "https://x.example/v1", "key": "k"})["outcome"] == "unreachable"


def test_the_key_is_never_sent_over_plain_http_to_a_remote_host(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, 200, {"data": []})
    with pytest.raises(keys.ApiKeyRejected) as err:
        keys.list_models({"base_url": "http://api.model.hd-aic.com/v1", "key": "k"})
    assert err.value.outcome == "insecure_scheme"
    assert calls == []


def test_a_missing_key_is_rejected_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, 200, {"data": []})
    with pytest.raises(keys.ApiKeyRejected):
        keys.list_models({"base_url": "https://x.example/v1", "key": " "})
    assert calls == []


def test_a_malformed_list_is_unexpected(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, 200, {"models": "nope"})
    assert keys.list_models({"base_url": "https://x.example/v1", "key": "k"})["outcome"] == "unexpected_response"
