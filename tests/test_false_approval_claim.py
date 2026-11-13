"""A finished turn must not claim an approval card that was never requested."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from olga_companion.agent import chat, history, pending_approvals, session_token
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.llm.protocol import StreamResult
from olga_companion.sidecar import app

NOTICE = "승인 요청이 아직 만들어지지 않았습니다. 저장하려면 다시 요청하세요."
CLAIM = "검증과 컴파일은 끝났고, 저장 승인 카드만 올려 두었습니다. 승인 카드에서 승인해 주세요."
NEUTRAL = "승인 카드는 저장 전에 사람이 확인하는 화면입니다. 물리값은 직접 입력해야 합니다."

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
        return self._script.pop(0)


@pytest.fixture
def token():
    return session_token.boot_token()


@pytest.fixture(autouse=True)
def _reset_builder():
    yield
    chat.set_client_builder(None)
    pending_approvals.revoke_all()


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


def _finish(token: str, text: str) -> tuple[str, str]:
    chat.set_client_builder(lambda _p, _m, _v: FakeApiClient([StreamResult(text=text)]))
    session_id = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "저장해 주세요"},
        headers={"X-Session-Token": token},
    )
    assert response.status_code == 200
    done = next(data for event, data in _parse_sse(response.text) if event == "done")
    return session_id, str(done.get("text", ""))


def test_prompt_contains_approval_followthrough_and_label_proposal() -> None:
    lowered = SYSTEM_PROMPT.lower()

    assert "never say an approval card exists unless" in lowered
    assert "call case_publish in the same turn" in lowered
    assert "inlet, outlet, main, pipe_1, and feed" in lowered
    assert "accept or change" in lowered
    assert "a physical value is used only after the user states or accepts it" in " ".join(lowered.split())
    assert "never put a value the user has not stated or accepted into a tool call" in " ".join(lowered.split())


@pytest.mark.parametrize("claim", [CLAIM, "I raised an approval card and it is waiting for you."])
def test_guard_appends_notice_when_the_turn_claims_a_card_and_none_is_pending(
    token: str, claim: str
) -> None:
    session_id, text = _finish(token, claim)

    assert text.startswith(claim)
    assert text.endswith(NOTICE)
    stored = next(
        record["text"]
        for record in history.read(session_id)
        if record.get("record") == "assistant"
    )
    assert stored == text


def test_guard_notices_a_claim_when_only_an_older_approval_is_pending(token: str) -> None:
    chat.set_client_builder(lambda _p, _m, _v: FakeApiClient([StreamResult(text=CLAIM)]))
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
        json={"session_id": session_id, "message": "저장해 주세요"},
        headers={"X-Session-Token": token},
    )

    done = next(data for event, data in _parse_sse(response.text) if event == "done")
    assert done["text"].startswith(CLAIM)
    assert done["text"].endswith(NOTICE)


def test_guard_leaves_a_neutral_explanation_of_approvals(token: str) -> None:
    _session_id, text = _finish(token, NEUTRAL)

    assert text == NEUTRAL
    assert NOTICE not in text
