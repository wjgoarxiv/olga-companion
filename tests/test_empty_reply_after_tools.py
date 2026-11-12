"""A turn whose provider goes quiet right after a tool result is asked once to answer.

Hyper-real round 5 (2026-11-11, build E, xai grok-4.7): after the run card was approved
the continuation called results_inventory and results_load, then returned no text and no
tool call. The chat stopped on the results_load card with no answer and no notice; the
next user message got an empty reply as well.
"""

from __future__ import annotations

import asyncio

from olga_companion.agent import runtime, step_follow_up
from olga_companion.llm.protocol import StreamResult, ToolCall


class FakeConversation:
    def __init__(self) -> None:
        self.turns: list[tuple] = []

    def add_user_message(self, text, images=None) -> None:
        self.turns.append(("user", text))

    def add_assistant_response(self, text, tool_calls=None, thought_signature=None) -> None:
        self.turns.append(("assistant", text, tool_calls))

    def add_tool_result(self, call_id, name, result) -> None:
        self.turns.append(("tool_result", call_id, name, result))


class FakeApiClient:
    def __init__(self, script: list[StreamResult]) -> None:
        self._script = list(script)
        self.calls = 0
        self.conversation = FakeConversation()

    def create_conversation(self, model: str = "") -> FakeConversation:
        return self.conversation

    async def stream_generate(self, **kwargs) -> StreamResult:
        result = self._script[self.calls]
        self.calls += 1
        return result


def _run(client: FakeApiClient, *, seed_user: bool = True):
    async def collect():
        return [
            event
            async for event in runtime.run_turn(
                client, "결과는 어떻게 됐나요?", conversation=client.conversation, seed_user=seed_user
            )
        ]

    return asyncio.run(collect())


TOOL_STEP = StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")])


def test_an_empty_reply_after_a_tool_result_is_asked_to_answer_once() -> None:
    client = FakeApiClient([TOOL_STEP, StreamResult(text=""), StreamResult(text="HOL 최댓값은 129 m입니다.")])
    events = _run(client)
    assert client.calls == 3
    assert ("user", step_follow_up.ANSWER_AFTER_TOOLS_MESSAGE) in client.conversation.turns
    assert events[-1].data["text"] == "HOL 최댓값은 129 m입니다."


def test_the_continuation_after_an_approval_is_asked_too() -> None:
    client = FakeApiClient([TOOL_STEP, StreamResult(text=""), StreamResult(text="계산이 끝났습니다.")])
    events = _run(client, seed_user=False)
    assert client.calls == 3
    assert events[-1].data["text"] == "계산이 끝났습니다."


def test_a_second_empty_reply_ends_the_turn_without_a_loop() -> None:
    client = FakeApiClient([TOOL_STEP, StreamResult(text=""), StreamResult(text="")])
    events = _run(client)
    assert client.calls == 3
    assert events[-1].type == "done"
    assert events[-1].data["text"] == ""


def test_an_empty_first_reply_with_no_tools_is_left_to_the_notice() -> None:
    client = FakeApiClient([StreamResult(text="")])
    _run(client)
    assert client.calls == 1


def test_the_answer_ask_has_its_own_chance_after_a_stall_follow_up() -> None:
    # Distribution demo 08 (grok-4.7): the turn had already used its one follow-up on an
    # announced step, so the empty reply after results_series ended on the notice.
    stalled = StreamResult(text="같은 값으로 케이스 정의를 검사합니다.")
    client = FakeApiClient([stalled, TOOL_STEP, StreamResult(text=""), StreamResult(text="압력 강하는 47492.8 Pa입니다.")])
    events = _run(client)
    assert client.calls == 4
    assert ("user", step_follow_up.FOLLOW_UP_MESSAGE) in client.conversation.turns
    assert ("user", step_follow_up.ANSWER_AFTER_TOOLS_MESSAGE) in client.conversation.turns
    assert events[-1].data["text"] == "압력 강하는 47492.8 Pa입니다."


def test_each_ask_is_still_made_only_once() -> None:
    stalled = StreamResult(text="같은 값으로 케이스 정의를 검사합니다.")
    client = FakeApiClient([stalled, TOOL_STEP, StreamResult(text=""), TOOL_STEP, StreamResult(text="")])
    events = _run(client)
    assert client.calls == 5
    asks = [turn for turn in client.conversation.turns if turn == ("user", step_follow_up.ANSWER_AFTER_TOOLS_MESSAGE)]
    assert len(asks) == 1
    assert events[-1].type == "done"
