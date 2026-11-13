"""An empty provider continuation after an approved action shows the empty-reply notice.

Review of the round-3 empty-reply fix (2026-11-11): /api/chat gained the notice, but the
continuation that runs after a card is approved kept its own `done` handling, so an
empty answer there still left the chat silent.
"""
from __future__ import annotations

import anyio

from olga_companion.agent import approval_event_persistence, chat, history, runtime


def _persist(monkeypatch, events, locale="ko"):
    async def provider_events(*_args, **_kwargs):
        for event in events:
            yield event

    monkeypatch.setattr(approval_event_persistence.runtime, "run_turn", provider_events)
    session_id = history.new_session("continuation empty reply")
    streamed = anyio.run(
        approval_event_persistence.persist_runtime_events,
        object(),
        "model",
        object(),
        session_id,
        {"turn_id": "turn-1", "request_id": "request-1", "locale": locale},
        None,
    )
    return streamed, history.read(session_id)


def _assistant_texts(records):
    return [r.get("text") for r in records if r.get("record") == "assistant"]


def test_an_empty_continuation_shows_and_stores_the_notice(monkeypatch) -> None:
    streamed, records = _persist(monkeypatch, [runtime.AgentEvent("done", {"text": ""})])
    assert streamed[-1]["data"]["text"] == chat.EMPTY_REPLY_NOTICE
    assert _assistant_texts(records) == [chat.EMPTY_REPLY_NOTICE]


def test_an_empty_english_continuation_uses_the_english_notice(monkeypatch) -> None:
    streamed, _ = _persist(monkeypatch, [runtime.AgentEvent("done", {"text": ""})], locale="en")
    assert streamed[-1]["data"]["text"] == chat.EMPTY_REPLY_NOTICE_EN


def test_a_continuation_that_ends_on_a_tool_result_shows_the_notice(monkeypatch) -> None:
    # Round 5 (build E): the continuation read results_load, then said nothing; the chat
    # stopped on the tool card with no answer.
    events = [
        runtime.AgentEvent("tool_call", {"name": "results_inventory", "call_id": "c1", "args": {}}),
        runtime.AgentEvent("tool_result", {"name": "results_inventory", "call_id": "c1", "result": {}}),
        runtime.AgentEvent("done", {"text": ""}),
    ]
    streamed, records = _persist(monkeypatch, events)
    assert streamed[-1]["data"]["text"] == chat.EMPTY_REPLY_NOTICE
    assert _assistant_texts(records)[-1] == chat.EMPTY_REPLY_NOTICE


def test_a_continuation_that_ends_on_a_text_after_tools_keeps_no_notice(monkeypatch) -> None:
    events = [
        runtime.AgentEvent("text", {"text": "결과를 읽겠습니다."}),
        runtime.AgentEvent("tool_call", {"name": "results_inventory", "call_id": "c1", "args": {}}),
        runtime.AgentEvent("tool_result", {"name": "results_inventory", "call_id": "c1", "result": {}}),
        runtime.AgentEvent("text", {"text": "결과는 2건입니다."}),
        runtime.AgentEvent("done", {"text": "결과는 2건입니다."}),
    ]
    streamed, records = _persist(monkeypatch, events)
    assert streamed[-1]["data"]["text"] == "결과는 2건입니다."
    assert chat.EMPTY_REPLY_NOTICE not in _assistant_texts(records)


def test_a_continuation_with_text_is_unchanged(monkeypatch) -> None:
    events = [
        runtime.AgentEvent("text", {"text": "계산이 끝났습니다."}),
        runtime.AgentEvent("done", {"text": "계산이 끝났습니다."}),
    ]
    streamed, _ = _persist(monkeypatch, events)
    assert streamed[-1]["data"]["text"] == "계산이 끝났습니다."
