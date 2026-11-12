"""Replay keeps every tool call answered before the conversation moves on.

OpenAI-compatible providers refuse (400) an assistant message with tool_calls that is not
followed by one tool message per call id. A user may type while an approval card waits,
so the persisted order can be call -> user -> result.
"""
from __future__ import annotations

import json

from olga_companion.agent import chat_replay
from olga_companion.llm.openai_chat_adapter import OpenAIChatConversationBuilder


class _Client:
    def create_conversation(self, model: str = "") -> OpenAIChatConversationBuilder:
        return OpenAIChatConversationBuilder()


def _assert_provider_order(messages: list[dict]) -> None:
    """The OpenAI Chat rule: tool_calls are answered right away, each id exactly once."""
    index = 0
    while index < len(messages):
        message = messages[index]
        assert message["role"] != "tool", f"tool message without its call at {index}"
        index += 1
        if message["role"] == "assistant" and message.get("tool_calls"):
            ids = [call["id"] for call in message["tool_calls"]]
            answered = []
            while index < len(messages) and messages[index]["role"] == "tool":
                answered.append(messages[index]["tool_call_id"])
                index += 1
            assert answered == ids, (ids, answered)


def _call(call_id: str, name: str = "run_execute") -> dict:
    return {
        "record": "assistant", "text": "",
        "tool_calls": [{"name": name, "args": {"source": "a.genkey"}, "call_id": call_id}],
    }


def _event_call(call_id: str, name: str = "run_execute") -> dict:
    return {"record": "event", "type": "tool_call", "name": name, "call_id": call_id, "args": {}}


def _result(call_id: str, name: str = "run_execute") -> dict:
    return {"record": "event", "type": "tool_result", "name": name, "call_id": call_id,
            "result": {"run_id": "r1", "state": "running"}}


def _pending(call_id: str, name: str = "run_execute") -> dict:
    return {"record": "approval", "pending_id": "p1", "call_id": call_id, "name": name, "state": "pending"}


def _rebuild(records: list[dict]) -> list[dict]:
    return chat_replay.rebuild_conversation(_Client(), "m", records).get_request_payload()


def test_a_message_typed_while_an_approval_waits_is_replayed_after_a_placeholder_result() -> None:
    messages = _rebuild([
        {"record": "user", "text": "run it"}, _call("c1"), _event_call("c1"), _pending("c1"),
        {"record": "user", "text": "Run it now please."},
    ])

    _assert_provider_order(messages)
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "user"]
    placeholder = json.loads(messages[2]["content"])
    assert placeholder["state"] == "awaiting_approval"


def test_a_result_recorded_after_the_typed_message_moves_up_to_its_call() -> None:
    messages = _rebuild([
        {"record": "user", "text": "run it"}, _call("c1"), _event_call("c1"), _pending("c1"),
        {"record": "user", "text": "Run it now please."},
        {"record": "error", "message": "provider refused"},
        {"record": "approval", "pending_id": "p1", "call_id": "c1", "result": {"run_id": "r1"}},
        _result("c1"),
    ])

    _assert_provider_order(messages)
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "user"]
    assert json.loads(messages[2]["content"]) == {"run_id": "r1", "state": "running"}


def test_an_unanswered_call_at_the_end_is_closed_before_a_new_user_message() -> None:
    conversation = chat_replay.rebuild_conversation(
        _Client(), "m", [{"record": "user", "text": "go"}, _call("c1"), _pending("c1")],
    )
    conversation.add_user_message("What is it waiting for?")
    messages = conversation.get_request_payload()

    _assert_provider_order(messages)
    assert json.loads(messages[2]["content"])["state"] == "awaiting_approval"


def test_a_call_with_no_approval_and_no_result_reads_as_interrupted() -> None:
    messages = _rebuild([
        {"record": "user", "text": "go"}, _call("c1", "case_draft_review"),
        {"record": "user", "text": "again"},
    ])

    _assert_provider_order(messages)
    assert json.loads(messages[2]["content"])["state"] == "no_result"


def test_two_calls_in_one_message_are_answered_in_call_order() -> None:
    both = {
        "record": "assistant", "text": "",
        "tool_calls": [
            {"name": "case_edit_plan", "args": {}, "call_id": "a"},
            {"name": "case_draft_review", "args": {}, "call_id": "b"},
        ],
    }
    messages = _rebuild([
        {"record": "user", "text": "go"}, both, _result("b", "case_draft_review"),
        _result("a", "case_edit_plan"), {"record": "user", "text": "next"},
    ])

    _assert_provider_order(messages)
    assert [m["tool_call_id"] for m in messages if m["role"] == "tool"] == ["a", "b"]


def test_ordinary_history_replays_unchanged() -> None:
    records = [
        {"record": "user", "text": "go"}, _call("c1"), _event_call("c1"), _result("c1"),
        {"record": "assistant", "text": "Started."}, {"record": "user", "text": "thanks"},
    ]
    messages = _rebuild(records)

    _assert_provider_order(messages)
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant", "user"]


def test_an_expired_approval_does_not_read_as_still_waiting() -> None:
    messages = _rebuild([
        {"record": "user", "text": "go"}, _call("c1"), _pending("c1"),
        {"record": "approval", "pending_id": "p1", "call_id": "c1", "state": "expired"},
        {"record": "user", "text": "hello?"},
    ])

    _assert_provider_order(messages)
    assert json.loads(messages[2]["content"])["state"] == "no_result"
