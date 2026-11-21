"""Live draft: provider text deltas reach the UI as `draft` events and never reach history.

Offline: every provider is a scripted fake. The draft carries only answer text (never
reasoning), is redacted like failure text, and is replaced by the final text.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient

from olga_companion.agent import chat, history, pending_approvals, runtime, session_token
from olga_companion.agent.chat_singleflight import session_single_flight_sync
from olga_companion.llm.protocol import StreamResult
from olga_companion.sidecar import app

client = TestClient(app)


class FakeConversation:
    def add_user_message(self, text, images=None): ...
    def add_assistant_response(self, text, tool_calls=None, thought_signature=None): ...
    def add_tool_result(self, call_id, name, result): ...


class DeltaClient:
    """Streams scripted deltas through `on_token`, then returns the final result."""

    def __init__(self, deltas, result, *, thinking_deltas=()):
        self._deltas = list(deltas)
        self._result = result
        self._thinking = list(thinking_deltas)
        self.saw_on_token = False

    def create_conversation(self, model=""):
        return FakeConversation()

    async def stream_generate(self, **kwargs):
        on_token = kwargs.get("on_token")
        on_thinking = kwargs.get("on_thinking")
        self.saw_on_token = on_token is not None
        for piece in self._thinking:
            if on_thinking:
                await on_thinking(piece)
        for piece in self._deltas:
            if on_token:
                await on_token(piece)
            await asyncio.sleep(0)
        return self._result


class HangingClient:
    """Emits one delta, then waits forever; records that it was cancelled."""

    def __init__(self):
        self.cancelled = False

    def create_conversation(self, model=""):
        return FakeConversation()

    async def stream_generate(self, **kwargs):
        await kwargs["on_token"]("half an answer")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _collect(client_obj, **kwargs):
    async def go():
        events = []
        async for event in runtime.run_turn(client_obj, "hi", **kwargs):
            events.append(event)
        return events

    return asyncio.run(go())


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


def _draft_text(events) -> str:
    return "".join(e.data["text"] for e in events if e.type == "draft")


@pytest.fixture(autouse=True)
def _reset():
    session_token.boot_token()
    yield
    chat.set_client_builder(None)
    pending_approvals.revoke_all()


def _chat(deltas, result, *, thinking_deltas=()):
    token = session_token.boot_token()
    chat.set_client_builder(
        lambda _p, _m, _v: DeltaClient(deltas, result, thinking_deltas=thinking_deltas)
    )
    sid = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]
    response = client.post(
        "/api/chat",
        json={"session_id": sid, "message": "hi"},
        headers={"X-Session-Token": token},
    )
    assert response.status_code == 200
    return sid, _parse_sse(response.text)


def test_draft_events_arrive_before_the_final_text():
    sid, events = _chat(["안녕", "하세요 ", "OLGA"], StreamResult(text="안녕하세요 OLGA"))
    types = [name for name, _ in events]
    assert "draft" in types, types
    assert types.index("draft") < types.index("text") < types.index("done")
    assert "".join(data["text"] for name, data in events if name == "draft") == "안녕하세요 OLGA"
    assert next(data for name, data in events if name == "done")["text"] == "안녕하세요 OLGA"


def test_run_turn_does_not_stream_drafts_unless_asked():
    events = _collect(DeltaClient(["a", "b"], StreamResult(text="ab")))
    assert [e.type for e in events] == ["text", "done"]


def test_a_secret_split_across_two_deltas_is_redacted():
    secret = "sk-abcdefghijklmnop1234"
    for deltas in (
        ["key is sk-abcdef", "ghijklmnop1234 ok"],
        ["key is sk-", "abcdefghijklmnop1234 ok"],
        ["use Bearer ", "abcdefghijklmnop1234 now"],
        ["id " + "a" * 25, "b" * 25 + " end"],
    ):
        events = _collect(
            DeltaClient(deltas, StreamResult(text="done")), stream_draft=True
        )
        shown = _draft_text(events)
        assert secret not in shown, deltas
        assert "abcdefghijklmnop1234" not in shown, deltas
        assert "a" * 25 + "b" * 25 not in shown, deltas
        assert "<redacted>" in shown, (deltas, shown)
        assert shown.startswith(("key is ", "use ", "id ")), shown


def test_plain_deltas_pass_through_unchanged_including_the_tail():
    events = _collect(
        DeltaClient(["The pipe ", "has ", "3 branches"], StreamResult(text="x")),
        stream_draft=True,
    )
    assert _draft_text(events) == "The pipe has 3 branches"


def test_history_never_holds_a_draft():
    sid, events = _chat(["half ", "way"], StreamResult(text="final answer"))
    records = history.read(sid)
    assert [r["record"] for r in records if r["record"] in {"assistant", "event"}] == ["assistant"]
    assert not any("draft" in json.dumps(r) for r in records), records
    assert next(r for r in records if r["record"] == "assistant")["text"] == "final answer"


def test_a_stopped_turn_cancels_the_stream_and_ends_with_no_draft_record():
    hanging = HangingClient()
    token = session_token.boot_token()
    chat.set_client_builder(lambda _p, _m, _v: hanging)
    sid = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]

    async def go():
        seen = []
        stream = chat.run_chat_turn(
            sid, "hi", provider="openai", model="m", variant="", locale="ko"
        )

        async def consume():
            async for event in stream:
                seen.append(event)

        task = asyncio.create_task(consume())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if any(e.type == "draft" for e in seen):
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)
        return seen

    seen = asyncio.run(go())
    assert any(e.type == "draft" for e in seen), "the draft reached the consumer before the stop"
    assert hanging.cancelled, "the provider stream was cancelled with the turn"
    assert not [e for e in seen if e.type in {"text", "done"}]
    records = history.read(sid)
    assert not any(r["record"] == "assistant" for r in records), records
    assert not any("half an answer" in json.dumps(r) for r in records), records


def test_reasoning_text_never_becomes_a_draft():
    events = _collect(
        DeltaClient(
            ["visible"], StreamResult(text="visible"), thinking_deltas=["secret reasoning"]
        ),
        stream_draft=True,
    )
    assert _draft_text(events) == "visible"


def test_phase_frame_follows_open_once_the_session_lock_is_held():
    sid, events = _chat(["a"], StreamResult(text="a"))
    names = [name for name, _ in events]
    assert names[0] == "open"
    assert ("phase", {"phase": "model"}) in events
    assert names.index("phase") < names.index("draft")


def test_phase_frame_says_queued_while_another_turn_holds_the_session():
    token = session_token.boot_token()
    chat.set_client_builder(lambda _p, _m, _v: DeltaClient(["a"], StreamResult(text="a")))
    sid = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]
    release = threading.Event()
    held = threading.Event()

    def hold():
        with session_single_flight_sync(sid):
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)

    async def go():
        stream = chat.run_chat_turn(
            sid, "hi", provider="openai", model="m", variant="", locale="ko"
        )
        first = await asyncio.wait_for(stream.__anext__(), 2)
        release.set()
        rest = [event async for event in stream]
        return first, rest

    try:
        first, rest = asyncio.run(go())
    finally:
        release.set()
        holder.join(5)
    assert (first.type, first.data) == ("phase", {"phase": "queued"})
    phases = [e.data["phase"] for e in rest if e.type == "phase"]
    assert phases == ["model"], phases
