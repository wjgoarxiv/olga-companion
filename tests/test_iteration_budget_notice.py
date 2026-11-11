"""A turn stopped by the iteration budget tells the user so, in the turn's language.

Hyper-real round 4 (2026-11-11): the model retried profile reads until the budget ran out;
the turn ended with an empty answer after a tool card and the chat just stopped.
"""
from __future__ import annotations

import asyncio

from olga_companion.agent import runtime
from olga_companion.llm.protocol import StreamResult, ToolCall


class _Conversation:
    def add_user_message(self, text, images=None): ...
    def add_assistant_response(self, text, tool_calls=None, thought_signature=None): ...
    def add_tool_result(self, call_id, name, result): ...


class _Client:
    def create_conversation(self, model=""):
        return _Conversation()

    async def stream_generate(self, **kwargs):
        return StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c")])


def _done(locale: str):
    async def collect():
        return [e async for e in runtime.run_turn(_Client(), "loop", max_iterations=2, locale=locale)]

    return asyncio.run(collect())[-1]


def test_the_budget_stop_says_so_in_korean() -> None:
    done = _done("ko")
    assert done.type == "done"
    assert done.data["text"] == runtime.BUDGET_STOP_MESSAGE
    assert "budget" in done.data["note"]


def test_the_budget_stop_says_so_in_english() -> None:
    assert _done("en").data["text"] == runtime.BUDGET_STOP_MESSAGE_EN
