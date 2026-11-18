"""Bounded replay contracts for oversized assistant tool batches."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from olga_companion.agent import chat_replay, history
from olga_companion.agent.history_policy import MAX_RECORD_BYTES, MAX_STRING_CHARS


class RecordingConversation:
    def add_user_message(self, text: str, images: list[bytes] | None = None) -> None:
        return

    def add_assistant_response(
        self, text: str, tool_calls=None, thought_signature=None
    ) -> None:
        pytest.fail("replay must stop before using truncated provider evidence")

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        return


class RecordingClient:
    def create_conversation(self, model: str = "") -> RecordingConversation:
        return RecordingConversation()


@pytest.fixture
def isolated_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    yield tmp_path


def test_oversized_assistant_preserves_batch_identity_and_fails_replay_closed(
    isolated_history: Path,
) -> None:
    # Given: one ordinary call and one call whose arguments exceed the record cap.
    session_id = history.new_session("oversized assistant")
    tool_calls = [
        {
            "name": "results_load", "args": {"path": "case.ppl"},
            "call_id": "load-1", "raw_arguments": '{"path":"case.ppl"}',
            "item_id": "item-load",
        },
        {
            "name": "case_modify",
            "args": {
                "changes": {
                    f"field-{index}": "x" * (MAX_STRING_CHARS + 1)
                    for index in range(9)
                }
            },
            "call_id": "modify-1", "raw_arguments": "{}", "item_id": "item-modify",
        },
    ]

    # When: the oversized provider assistant response crosses persistence.
    history.append(
        session_id,
        {
            "record": "assistant", "text": "Applying both calls.",
            "tool_calls": tool_calls, "thought_signature": "signature-identity",
        },
    )
    record = history.read(session_id)[1]

    # Then: order/identity/signature remain bounded, but unsafe replay stops explicitly.
    assert [call["call_id"] for call in record["tool_calls"]] == ["load-1", "modify-1"]
    assert record["thought_signature"] == "signature-identity"
    assert record["replay_blocked"] is True
    assert len(json.dumps(record).encode("utf-8")) <= MAX_RECORD_BYTES
    with pytest.raises(chat_replay.ChatReplayIntegrityError, match="oversized"):
        chat_replay.rebuild_conversation(RecordingClient(), "model", history.read(session_id))
