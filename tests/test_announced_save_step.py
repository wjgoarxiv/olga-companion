"""A finished turn must not stop on a sentence that only promises the save step."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from olga_companion.agent import chat, history, pending_approvals, session_token
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.llm.protocol import StreamResult, ToolCall
from olga_companion.sidecar import app

NOTICE = "다음 단계가 아직 실행되지 않았습니다. '계속'이라고 보내면 이어서 진행합니다."
FALSE_NOTICE = "승인 요청이 아직 만들어지지 않았습니다. 저장하려면 다시 요청하세요."
LIVE = (
    "같은 폴더에 beginner_pipeline_test_v2.genkey로 저장하는 승인 계획을 올리겠습니다. "
    "실행은 하지 않습니다."
)
PLAIN = "검증과 컴파일이 끝났습니다. 결과 파일은 아직 없습니다."
EXPLANATION = "저장은 승인 뒤에 이뤄지는 계획입니다. 값은 사용자가 정합니다."
PAST = "같은 폴더에 저장하는 승인 계획을 올렸습니다."
FILE_ONLY = "다음 파일을 올리겠습니다."

client = TestClient(app)


class FakeConversation:
    def add_user_message(self, text, images=None): ...
    def add_assistant_response(self, text, tool_calls=None, thought_signature=None): ...
    def add_tool_result(self, call_id, name, result): ...


class FakeApiClient:
    def __init__(self, script):
        self._script = list(script)

    def create_conversation(self, model=""):
        return FakeConversation()

    async def stream_generate(self, **kwargs):
        # A stalled model keeps stalling: the runtime's one automatic follow-up
        # round gets the same last answer again, so the notice is still judged.
        return self._script.pop(0) if len(self._script) > 1 else self._script[0]


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        etype = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                etype = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if etype:
            events.append((etype, data))
    return events


def _post(token: str, script: list[StreamResult]) -> tuple[str, str]:
    chat.set_client_builder(lambda _p, _m, _v: FakeApiClient(script))
    session_id = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "검증하고 컴파일한 뒤 저장 승인을 올려 주세요"},
        headers={"X-Session-Token": token},
    )
    assert response.status_code == 200
    done = next(data for event, data in _parse_sse(response.text) if event == "done")
    return session_id, str(done.get("text", ""))


def setup_function() -> None:
    session_token.boot_token()


def teardown_function() -> None:
    chat.set_client_builder(None)
    pending_approvals.revoke_all()


def test_prompt_continues_a_clean_save_request_in_the_same_turn() -> None:
    lowered = SYSTEM_PROMPT.lower()

    assert "when the user asked for a save approval card" in lowered
    assert "case_spec_validate and case_spec_compile are clean" in lowered
    assert "continue in the same turn: call case_edit_plan, then case_publish" in lowered
    assert "never end a turn on a sentence that only announces the next tool step" in lowered


def test_live_announcement_appends_the_continue_line() -> None:
    token = session_token.boot_token()
    session_id, text = _post(token, [StreamResult(text=LIVE)])

    assert text.startswith(LIVE)
    assert text.endswith(NOTICE)
    assert FALSE_NOTICE not in text
    stored = next(
        record["text"]
        for record in history.read(session_id)
        if record.get("record") == "assistant"
    )
    assert stored == text


@pytest.mark.parametrize(
    ("verb", "noun"),
    [
        ("올리겠습니다", "승인"),
        ("요청하겠습니다", "저장"),
        ("만들겠습니다", "계획"),
    ],
)
def test_future_save_verbs_append_the_line(verb: str, noun: str) -> None:
    token = session_token.boot_token()
    spoken = f"다음으로 {noun} 단계를 {verb}."
    _session_id, text = _post(token, [StreamResult(text=spoken)])

    assert text.startswith(spoken)
    assert text.endswith(NOTICE)


def test_announcement_after_an_earlier_tool_still_appends_the_line() -> None:
    token = session_token.boot_token()
    _session_id, text = _post(
        token,
        [
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text=LIVE),
        ],
    )

    assert text.startswith(LIVE)
    assert text.endswith(NOTICE)


def test_a_tool_that_follows_the_announcement_leaves_the_later_text() -> None:
    token = session_token.boot_token()
    _session_id, text = _post(
        token,
        [
            StreamResult(
                text=LIVE,
                tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")],
            ),
            StreamResult(text=PLAIN),
        ],
    )

    assert text == PLAIN
    assert NOTICE not in text


def test_an_older_approval_does_not_suppress_the_continue_line() -> None:
    token = session_token.boot_token()
    chat.set_client_builder(lambda _p, _m, _v: FakeApiClient([StreamResult(text=LIVE)]))
    session_id = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]
    pending_approvals.register(
        action_kind="case_publish",
        args={},
        call_id="already-pending",
        context_generation=0,
        session_id=session_id,
    )
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "저장 승인을 올려 주세요"},
        headers={"X-Session-Token": token},
    )

    done = next(data for event, data in _parse_sse(response.text) if event == "done")
    assert done["text"].startswith(LIVE)
    assert done["text"].endswith(NOTICE)


@pytest.mark.parametrize(
    "spoken",
    [
        "I'll request the save approval in this turn.",
        "I'll create a save plan for the new case.",
        "I'll raise an approval before anything is written.",
    ],
)
def test_english_save_promises_append_the_line(spoken: str) -> None:
    token = session_token.boot_token()
    _session_id, text = _post(token, [StreamResult(text=spoken)])

    assert text.startswith(spoken)
    assert text.endswith(NOTICE)
    assert FALSE_NOTICE not in text


def test_english_explanation_and_past_claim_stay_free_of_the_continue_line() -> None:
    token = session_token.boot_token()
    explanation = "The save plan is the reviewed diff before approval."
    _session_id, text = _post(token, [StreamResult(text=explanation)])

    assert text == explanation

    past = "I raised an approval card and it is waiting for you."
    _session_id, past_text = _post(token, [StreamResult(text=past)])
    assert NOTICE not in past_text


def test_pending_run_execute_does_not_suppress_a_save_announcement() -> None:
    token = session_token.boot_token()
    chat.set_client_builder(lambda _p, _m, _v: FakeApiClient([StreamResult(text=LIVE)]))
    session_id = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]
    pending_approvals.register(
        action_kind="run_execute",
        args={},
        call_id="run-pending",
        context_generation=0,
        session_id=session_id,
    )
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "저장 승인을 올려 주세요"},
        headers={"X-Session-Token": token},
    )

    done = next(data for event, data in _parse_sse(response.text) if event == "done")
    assert str(done["text"]).startswith(LIVE)
    assert str(done["text"]).endswith(NOTICE)


ASKS_FOR_VALUES = (
    "아래를 한 번에 답해 주시면 그 값 그대로 케이스 정의를 검사하고, "
    "통과하면 저장 승인 카드를 올리겠습니다.\n\n수평 배관 길이 m, 안지름 m, 구간 수."
)
ASKS_FOR_LIMIT = (
    "다음 증거 확인은 계산 실행입니다. 시간 제한을 말씀해 주시면 실행 승인 카드를 올리겠습니다."
)
ASKS_IN_ENGLISH = "Which inlet do you want? Once you confirm, I'll request the save approval."
# Round 15 (build P): a proposal list that asks for a yes got the continue line appended.
ASKS_TO_CONFIRM = (
    "케이스를 검증하기 전에 아래만 한 번 확인해 주세요. 수락하시면 그 값으로 검증한 뒤 "
    "저장 승인을 올리겠습니다. 저장 파일은 hr15_first.genkey입니다.\n\n"
    "입구는 닫힌 끝과 질량유량입니다."
)


@pytest.mark.parametrize("sample", [ASKS_FOR_VALUES, ASKS_FOR_LIMIT, ASKS_IN_ENGLISH, ASKS_TO_CONFIRM])
def test_a_turn_that_waits_on_the_user_gets_no_continue_line(sample: str) -> None:
    token = session_token.boot_token()
    _session_id, text = _post(token, [StreamResult(text=sample)])

    assert text == sample
    assert NOTICE not in text


@pytest.mark.parametrize(
    "spoken",
    [
        "검증이 끝났습니다. 저장 승인 카드를 올리겠습니다. 잠시만 기다려 주세요.",
        "I'll create the save plan next. If you see an error, tell me.",
    ],
)
def test_a_polite_aside_does_not_hide_a_stalled_promise(spoken: str) -> None:
    token = session_token.boot_token()
    _session_id, text = _post(token, [StreamResult(text=spoken)])

    assert text.startswith(spoken)
    assert text.endswith(NOTICE)


@pytest.mark.parametrize("sample", [PLAIN, EXPLANATION, PAST, FILE_ONLY])
def test_plain_explanations_stay_unchanged(sample: str) -> None:
    token = session_token.boot_token()
    _session_id, text = _post(token, [StreamResult(text=sample)])

    assert text == sample
    assert NOTICE not in text
