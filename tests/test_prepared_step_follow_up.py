"""A turn that prepares an approval step and then stops without asking for it is followed up once.

Live PVT 2026-11-16 (hr01): the assistant ran run_preview, wrote "실행 승인 카드를 올립니다."
and ended the turn without calling run_execute; the engineer had to ask again. The phrase
lists missed "올립니다" and "만들겠습니다", so the guard keys on the tool results of the turn,
not on the wording.
"""

from __future__ import annotations

import asyncio

import pytest

from olga_companion.agent import runtime, step_follow_up
from olga_companion.llm.protocol import StreamResult, ToolCall

from test_empty_reply_after_tools import FakeApiClient


def _run(client: FakeApiClient, monkeypatch: pytest.MonkeyPatch, output: dict | None = None):
    monkeypatch.setattr(runtime.tools, "dispatch", lambda name, args: output or {"ok": True})

    async def collect():
        return [
            event
            async for event in runtime.run_turn(client, "실행해 줘", conversation=client.conversation)
        ]

    return asyncio.run(collect())


def _step(name: str) -> StreamResult:
    return StreamResult(tool_calls=[ToolCall(name=name, args={}, call_id=f"c-{name}")])


@pytest.mark.parametrize("prepared", ["run_preview", "case_edit_plan"])
@pytest.mark.parametrize("text", ["실행 승인 카드를 올립니다.", "저장 카드를 만들겠습니다.", "Here is the preview."])
def test_a_prepared_step_without_its_request_is_followed_up_once(monkeypatch, prepared, text) -> None:
    client = FakeApiClient([_step(prepared), StreamResult(text=text), StreamResult(text="승인 카드를 확인해 주세요.")])
    events = _run(client, monkeypatch)
    assert client.calls == 3
    asks = [turn for turn in client.conversation.turns if turn[0] == "user" and turn[1].startswith("(automatic)")]
    assert asks == [("user", step_follow_up.prepared_step_message(prepared))]
    assert events[-1].data["text"] == "승인 카드를 확인해 주세요."


def test_a_reply_that_waits_on_the_user_is_not_followed_up(monkeypatch) -> None:
    client = FakeApiClient([_step("run_preview"), StreamResult(text="미리보기가 깨끗합니다. 실행할까요?")])
    _run(client, monkeypatch)
    assert client.calls == 2


def test_a_failed_preview_is_not_followed_up(monkeypatch) -> None:
    client = FakeApiClient([_step("run_preview"), StreamResult(text="미리보기에서 오류가 났습니다.")])
    _run(client, monkeypatch, {"error": "case not found"})
    assert client.calls == 2


def test_a_plain_answer_without_tools_costs_no_extra_call(monkeypatch) -> None:
    client = FakeApiClient([StreamResult(text="GASFRACTION은 기체 질량 분율입니다.")])
    _run(client, monkeypatch)
    assert client.calls == 1


def test_a_read_only_tool_is_not_a_prepared_step(monkeypatch) -> None:
    client = FakeApiClient([_step("run_detect"), StreamResult(text="OLGA 2022.1.0이 설치되어 있습니다.")])
    _run(client, monkeypatch)
    assert client.calls == 2


def test_the_follow_up_is_made_only_once(monkeypatch) -> None:
    client = FakeApiClient([_step("run_preview"), StreamResult(text="올립니다."), StreamResult(text="올립니다.")])
    events = _run(client, monkeypatch)
    assert client.calls == 3
    assert events[-1].type == "done"
