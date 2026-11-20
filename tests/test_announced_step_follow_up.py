"""A turn that ends by announcing its next tool step gets one automatic follow-up round.

Hyper-real rounds 1 and 2 (2026-11-11, xai grok-4.7) ended turns on "표를 새 파일로 복사하고,
같은 값으로 케이스 정의를 검사합니다." and "… 검증에 넣겠습니다." with no tool call, three
times in each round; the prompt already forbids it and the user had to type "계속".
"""

from __future__ import annotations

import asyncio

import pytest

from olga_companion.agent import runtime
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
        self.conversation: FakeConversation | None = None

    def create_conversation(self, model: str = "") -> FakeConversation:
        self.conversation = FakeConversation()
        return self.conversation

    async def stream_generate(self, **kwargs) -> StreamResult:
        result = self._script[self.calls]
        self.calls += 1
        return result


def _run(client: FakeApiClient, message: str = "네 진행해 주세요"):
    async def collect():
        return [event async for event in runtime.run_turn(client, message)]

    return asyncio.run(collect())


def test_an_announced_check_gets_one_follow_up_round() -> None:
    client = FakeApiClient(
        [
            StreamResult(text="주신 값 그대로 둡니다.\n\n같은 값으로 케이스 정의를 검사합니다."),
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="OLGA를 찾았습니다."),
        ]
    )
    events = _run(client)
    assert [e.type for e in events] == ["text", "tool_call", "tool_result", "text", "done"]
    nudges = [turn for turn in client.conversation.turns[1:] if turn[0] == "user"]
    assert len(nudges) == 1


def test_an_announced_approval_request_is_followed_up() -> None:
    # Round 3: "저장 계획은 검증이 깨끗합니다. 승인 카드를 요청합니다." and no card.
    client = FakeApiClient(
        [
            StreamResult(text="저장 계획은 검증이 깨끗합니다. 승인 카드를 요청합니다."),
            StreamResult(text="Done."),
        ]
    )
    _run(client)
    assert client.calls == 2


def test_the_follow_up_happens_at_most_once_per_turn() -> None:
    stall = StreamResult(text="수락하신 값으로 다시 검사합니다.")
    client = FakeApiClient([stall, stall])
    events = _run(client)
    assert client.calls == 2
    assert events[-1].type == "done"


def test_a_turn_that_asks_the_user_is_not_followed_up() -> None:
    client = FakeApiClient([StreamResult(text="종료 600 s로 검사할까요?")])
    events = _run(client)
    assert client.calls == 1
    assert [e.type for e in events] == ["text", "done"]


def test_a_plain_answer_is_not_followed_up() -> None:
    client = FakeApiClient([StreamResult(text="압력강하는 4478 Pa입니다. 분포도 이어서 볼 수 있습니다.")])
    _run(client)
    assert client.calls == 1


def test_an_announcement_only_in_an_earlier_paragraph_is_not_followed_up() -> None:
    text = "실행이 끝나면 PT를 읽겠습니다.\n\n시뮬레이션 종료 시각을 알려 주세요."
    client = FakeApiClient([StreamResult(text=text)])
    _run(client)
    assert client.calls == 1


def test_an_empty_follow_up_keeps_the_stalled_text_as_the_turn_text() -> None:
    stalled = "같은 값으로 케이스 정의를 검사합니다."
    client = FakeApiClient([StreamResult(text=stalled), StreamResult(text="")])
    events = _run(client)
    assert events[-1].type == "done"
    assert events[-1].data["text"] == stalled


def test_no_follow_up_on_the_last_iteration() -> None:
    stalled = StreamResult(text="같은 값으로 케이스 정의를 검사합니다.")
    client = FakeApiClient([stalled])

    async def collect():
        return [e async for e in runtime.run_turn(client, "go", max_iterations=1)]

    events = asyncio.run(collect())
    assert client.calls == 1
    assert events[-1].data["text"] == stalled.text


@pytest.mark.parametrize(
    "text",
    ["이 도구는 케이스를 실행합니다.", "결과는 자동 저장합니다.", "I'll check the logs if it recurs."],
)
def test_descriptive_lines_are_not_followed_up(text: str) -> None:
    client = FakeApiClient([StreamResult(text=text)])
    _run(client)
    assert client.calls == 1


def test_english_announcement_is_followed_up_too() -> None:
    client = FakeApiClient(
        [
            StreamResult(text="I'll validate the case with the same values now."),
            StreamResult(text="Done."),
        ]
    )
    _run(client, "go on")
    assert client.calls == 2


# Round 4 (build D): after "제안대로 진행해 주세요." the turn ended on a restatement,
# "… 수락하신 대로 입구는 질량유량, … 20 m는 중심선 길이로 넣습니다. …", with no tool call.
ROUND_4_STALL = (
    "이번 메시지에 적으신 숫자는 20 °C, 20 m입니다. 수락하신 대로 입구는 질량유량, "
    "20 °C는 입구와 출구 둘 다, 20 m는 중심선 길이로 넣습니다. 출구 분율은 추천값인 "
    "기체 1, 물 0.980392입니다. 표는 일반 공기-물 표이며, 이 케이스 전용으로 만든 것이 아닙니다."
)


def test_an_acknowledged_go_ahead_with_no_call_is_followed_up() -> None:
    client = FakeApiClient(
        [
            StreamResult(text=ROUND_4_STALL),
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="검증했습니다."),
        ]
    )
    _run(client, "제안대로 진행해 주세요.")
    assert client.calls == 3


def test_an_acknowledgement_after_a_tool_call_is_a_finished_turn() -> None:
    client = FakeApiClient(
        [
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="수락하신 값으로 저장을 마쳤습니다."),
        ]
    )
    _run(client, "제안대로 진행해 주세요.")
    assert client.calls == 2


def test_an_acknowledged_validation_with_no_call_is_followed_up() -> None:
    # Round 6 (build I): "수락하신 값으로 명세를 검증합니다. 말씀하신 숫자는 …" and no call.
    stall = (
        "수락하신 값으로 명세를 검증합니다. 말씀하신 숫자는 150 mm, 500 m입니다. "
        "표는 일반 공기-물 표이며, 이 케이스 전용이 아닙니다."
    )
    client = FakeApiClient(
        [
            StreamResult(text=stall),
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="검증했습니다."),
        ]
    )
    _run(client, "전부 제안대로 해 주세요.")
    assert client.calls == 3


def test_an_echo_of_the_users_numbers_with_no_call_is_followed_up() -> None:
    # Round 13 (build N): after the user accepted every proposal, the turn ended on
    # "적으신 값은 25 °C, … 일반 공기-물 표 복사와 케이스 검사를 같이 진행합니다." and no call.
    stall = (
        "적으신 값은 25 °C, 1, 0.980392, 1, 0.980392, 4.6e-5 m, 3600 s, 50구간, "
        "표 파일 `hr13_air_water.tab`입니다. 일반 공기-물 표 복사와 케이스 검사를 같이 진행합니다."
    )
    client = FakeApiClient(
        [
            StreamResult(text=stall),
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="검사했습니다."),
        ]
    )
    _run(client, "막힌 입구 + 질량유량으로 해 주세요. 표를 복사해 주세요.")
    assert client.calls == 3


def test_a_closing_go_ahead_line_with_no_call_is_followed_up() -> None:
    # Round 14 (build O): the reply listed every value, then ended on
    # "일반 표 복사 승인과 케이스 명세 검증을 함께 진행합니다." and made no call.
    stall = (
        "입력하신 숫자는 그대로 사용합니다. 내경 100 mm, 길이 2 km입니다.\n\n"
        "이름: INLET, OUTLET, MAIN, PIPE_1, FEED\n\n"
        "일반 표 복사 승인과 케이스 명세 검증을 함께 진행합니다."
    )
    client = FakeApiClient(
        [
            StreamResult(text=stall),
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="검증했습니다."),
        ]
    )
    _run(client, "나머지는 제안대로 해도 됩니다.")
    assert client.calls == 3


def test_an_announced_run_request_after_an_approved_save_is_followed_up() -> None:
    # Round 14 (build O): the continuation after the approved save ended on
    # "hr14_double.genkey가 저장되었습니다. 실행 명령을 확인한 뒤 승인을 요청합니다." with no call.
    client = FakeApiClient(
        [
            StreamResult(text="hr14_double.genkey가 저장되었습니다. 실행 명령을 확인한 뒤 승인을 요청합니다."),
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="실행 명령을 확인했습니다."),
        ]
    )

    async def collect():
        conversation = client.create_conversation()
        return [e async for e in runtime.run_turn(client, "", conversation=conversation, seed_user=False)]

    asyncio.run(collect())
    assert client.calls == 3


def test_progress_named_in_an_earlier_paragraph_only_is_not_followed_up() -> None:
    text = "OLGA는 시간 간격을 줄이며 계산을 진행합니다.\n\n입구 압력은 5.2 bar입니다."
    client = FakeApiClient([StreamResult(text=text)])
    _run(client, "입구 압력은요")
    assert client.calls == 1


def test_an_echo_of_the_users_numbers_that_only_answers_is_not_followed_up() -> None:
    client = FakeApiClient([StreamResult(text="적으신 값은 30 bar입니다. 이 표의 상한 20 bar보다 높습니다.")])
    _run(client, "30 bar로 하면 되나요")
    assert client.calls == 1


def test_an_explanation_that_agrees_with_the_user_is_not_followed_up() -> None:
    # Review of R4-1: "말씀하신 대로" also opens a plain answer that promises no step.
    client = FakeApiClient([StreamResult(text="말씀하신 대로 100 bar는 이 표 범위보다 높습니다. 표 상한은 20 bar입니다.")])
    _run(client, "100 bar는 너무 높지 않나요")
    assert client.calls == 1


def test_an_acknowledgement_in_a_continuation_is_not_followed_up() -> None:
    # The turn after an approved card starts with no user message; "수락하신 대로 저장했습니다."
    # there closes the approved step.
    client = FakeApiClient([StreamResult(text="수락하신 대로 넣습니다. 저장은 끝났습니다.")])

    async def collect():
        conversation = client.create_conversation()
        return [e async for e in runtime.run_turn(client, "", conversation=conversation, seed_user=False)]

    asyncio.run(collect())
    assert client.calls == 1


def test_an_acknowledgement_that_asks_the_user_is_not_followed_up() -> None:
    client = FakeApiClient([StreamResult(text="수락하신 값으로 둡니다. 종료 시각도 3600 s로 둘까요?")])
    _run(client, "제안대로 진행해 주세요.")
    assert client.calls == 1
