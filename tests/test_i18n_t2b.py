"""Todo 2 follow-up: chat error texts follow the turn locale."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from olga_companion.agent import chat, history, runtime
from olga_companion.llm.protocol import StreamResult
from olga_companion.sidecar import app

client = TestClient(app)


class _Conversation:
    def add_user_message(self, *args, **kwargs) -> None:
        return None

    def add_assistant_response(self, *args, **kwargs) -> None:
        return None

    def add_tool_result(self, *args, **kwargs) -> None:
        return None

    def get_request_payload(self) -> list:
        return []


class _FailingClient:
    def __init__(self, message: str) -> None:
        self._message = message

    def create_conversation(self, model: str = "") -> _Conversation:
        return _Conversation()

    async def stream_generate(self, **kwargs) -> StreamResult:
        raise RuntimeError(self._message)


def _headers() -> dict[str, str]:
    token = client.get("/api/session/token").json()["token"]
    return {"X-Session-Token": token}


def _messages(response) -> str:
    texts = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                try:
                    texts.append(str(json.loads(line[6:]).get("message", "")))
                except json.JSONDecodeError:
                    pass
    return "\n".join(texts)


# ---------------------------------------------------------------- provider failure


def test_provider_failure_is_korean_by_default() -> None:
    message = runtime._provider_failure_message(400, "bad input")
    assert message.startswith("응답을 만들지 못했습니다. 공급자 연결을 확인하고 다시 시도하세요.")
    assert "제공자가 요청을 거절했습니다(400): bad input" in message


def test_provider_failure_english_reasons() -> None:
    denied = runtime._provider_failure_message(401, "nope", locale="en")
    assert denied == (
        "Generation failed. Check the provider connection and retry. "
        "Authentication was rejected."
    )
    limited = runtime._provider_failure_message(429, "slow", locale="en")
    assert limited.endswith("Rate limit exceeded.")
    rejected = runtime._provider_failure_message(400, "bad input", locale="en")
    assert rejected.endswith("The provider rejected the request (400): bad input")
    plain = runtime._provider_failure_message(None, "x", locale="en")
    assert plain == "Generation failed. Check the provider connection and retry."


def test_run_turn_failure_event_follows_locale() -> None:
    import asyncio

    async def _run(locale: str) -> list[runtime.AgentEvent]:
        failing = _FailingClient("error 401: denied")
        return [
            event
            async for event in runtime.run_turn(
                failing, "hi", model="m",
                conversation=_Conversation(), locale=locale,
            )
        ]

    ko = asyncio.run(_run("ko"))
    assert "인증이 거절됐습니다." in ko[-1].data["message"]
    assert ko[-1].data["message"].startswith("응답을 만들지 못했습니다.")
    en = asyncio.run(_run("en"))
    assert en[-1].data["message"].startswith("Generation failed.")
    assert "Authentication was rejected." in en[-1].data["message"]


# ---------------------------------------------------------------- not connected


def test_not_connected_error_follows_locale() -> None:
    chat.set_client_builder(lambda _p, _m, _v: None)
    try:
        ko_id = client.post(
            "/api/chat/session", json={"title": ""}, headers=_headers()
        ).json()["session_id"]
        ko = client.post(
            "/api/chat", json={"session_id": ko_id, "message": "hi"}, headers=_headers()
        )
        assert "연결되어 있지 않습니다" in _messages(ko)
        en_id = client.post(
            "/api/chat/session", json={"title": ""}, headers=_headers()
        ).json()["session_id"]
        en = client.post(
            "/api/chat",
            json={"session_id": en_id, "message": "hi", "locale": "en"},
            headers=_headers(),
        )
        assert "is not connected" in _messages(en)
        assert "AI provider" in _messages(en)
    finally:
        chat.set_client_builder(None)


def test_deleted_session_message_follows_locale() -> None:
    ko_id = client.post(
        "/api/chat/session", json={"title": ""}, headers=_headers()
    ).json()["session_id"]
    client.delete(f"/api/chat/session/{ko_id}", headers=_headers())
    ko = client.post(
        "/api/chat", json={"session_id": ko_id, "message": "hi"}, headers=_headers()
    )
    assert "삭제" in _messages(ko)
    en_id = client.post(
        "/api/chat/session", json={"title": ""}, headers=_headers()
    ).json()["session_id"]
    client.delete(f"/api/chat/session/{en_id}", headers=_headers())
    en = client.post(
        "/api/chat",
        json={"session_id": en_id, "message": "hi", "locale": "en"},
        headers=_headers(),
    )
    assert "has been deleted" in _messages(en)


# ---------------------------------------------------------------- notices


def test_guard_notices_follow_locale() -> None:
    ko_false = chat.guard_turn_text("승인 카드 raised", announced_unfollowed=False, registered_actions=set())
    assert "승인 요청이 아직 만들어지지 않았습니다" in ko_false
    en_false = chat.guard_turn_text(
        "승인 카드 raised", announced_unfollowed=False, registered_actions=set(), locale="en"
    )
    assert "has not been created yet" in en_false
    assert "승인 요청" not in en_false


def test_stale_message_follows_locale() -> None:
    assert "workspace" in runtime._stale_message("en").lower()
    assert runtime._stale_message("ko") == runtime.STALE_CONTEXT_MESSAGE
