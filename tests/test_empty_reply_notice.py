"""A turn whose model reply is empty says so instead of showing nothing.

Hyper-real round 3 (2026-11-11, xai grok-4.7): the user sent "계속 진행해 주세요." and the
provider returned no text and no tool call; the chat stayed silent and nothing was stored.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from olga_companion.agent import chat, history, pending_approvals, session_token
from olga_companion.llm.protocol import StreamResult, ToolCall
from olga_companion.sidecar import app

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


def _done(token: str, script: list[StreamResult]) -> tuple[str, str]:
    chat.set_client_builder(lambda _p, _m, _v: FakeApiClient(script))
    session_id = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "계속 진행해 주세요."},
        headers={"X-Session-Token": token},
    )
    assert response.status_code == 200
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        if "event: done" in lines:
            data = next(line[6:] for line in lines if line.startswith("data: "))
            return session_id, str(json.loads(data).get("text", ""))
    raise AssertionError("no done event")


def teardown_function() -> None:
    chat.set_client_builder(None)
    pending_approvals.revoke_all()


def test_an_empty_reply_gets_a_notice_and_is_stored() -> None:
    token = session_token.boot_token()
    session_id, text = _done(token, [StreamResult(text="")])
    assert text == chat.EMPTY_REPLY_NOTICE
    stored = [r["text"] for r in history.read(session_id) if r.get("record") == "assistant"]
    assert stored == [chat.EMPTY_REPLY_NOTICE]


def test_a_silent_end_after_a_tool_call_gets_the_notice() -> None:
    # Round 5 (build E): a turn that stopped on a tool card with no answer left the user
    # with nothing to read. The runtime asks once more; if that is empty too, say so.
    token = session_token.boot_token()
    _session_id, text = _done(
        token,
        [
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text=""),
            StreamResult(text=""),
        ],
    )
    assert text == chat.EMPTY_REPLY_NOTICE


def test_a_whitespace_only_end_after_a_tool_call_gets_the_notice() -> None:
    # Review of R5-1: the runtime treats "\n" as empty; the chat layer must agree.
    token = session_token.boot_token()
    _session_id, text = _done(
        token,
        [
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="\n"),
            StreamResult(text=" \n"),
        ],
    )
    assert text == chat.EMPTY_REPLY_NOTICE
