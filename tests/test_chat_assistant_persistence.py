"""Focused canonical assistant persistence contract for G002."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import sidecar
from olga_companion.agent import chat, history, session_token
from olga_companion.llm.protocol import StreamResult


class EmptyConversation:
    def add_user_message(self, text: str, images: list[bytes] | None = None) -> None:
        return

    def add_assistant_response(
        self, text: str, tool_calls=None, thought_signature=None
    ) -> None:
        return

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        return


class TextClient:
    def create_conversation(self, model: str = "") -> EmptyConversation:
        return EmptyConversation()

    async def stream_generate(self, **_kwargs) -> StreamResult:
        return StreamResult(text="One answer.")


@pytest.fixture
def isolated_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    chat.set_client_builder(lambda _provider, _model, _variant: TextClient())
    yield TestClient(sidecar.app)
    chat.set_client_builder(None)


def test_completed_turn_persists_one_assistant_record(
    isolated_chat: TestClient,
) -> None:
    # Given: a durable session receiving one plain provider response.
    headers = {"X-Session-Token": session_token.boot_token()}
    session_id = isolated_chat.post(
        "/api/chat/session", json={"title": "assistant once"}, headers=headers
    ).json()["session_id"]

    # When: the turn reaches both text and done SSE events.
    response = isolated_chat.post(
        "/api/chat",
        json={"session_id": session_id, "message": "Answer once."},
        headers=headers,
    )

    # Then: the canonical transcript contains one, not two, assistant records.
    assert response.status_code == 200
    records = history.read(str(session_id))
    assistants = [record for record in records if record.get("record") == "assistant"]
    assert len(assistants) == 1
    assistant = assistants[0]
    assert assistant.get("text") == "One answer."
    assert isinstance(assistant.get("sequence"), int)
    assert all(
        isinstance(assistant.get(key), str) and assistant[key]
        for key in ("turn_id", "request_id")
    )
