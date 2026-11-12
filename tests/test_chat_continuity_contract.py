"""RED contracts for durable, provider-neutral Chat continuity."""
from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from olga_companion import runner, sidecar
from olga_companion.agent import chat, history, pending_approvals, session_token
from olga_companion.llm.protocol import StreamResult, ToolCall

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class RecordedMessage:
    kind: Literal["user", "assistant", "tool_result"]
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


class RecordingConversation:
    """Mutable provider transcript recorder used only by the fake client."""

    def __init__(self) -> None:
        self.messages: list[RecordedMessage] = []

    def add_user_message(self, text: str, images: list[bytes] | None = None) -> None:
        self.messages.append(RecordedMessage("user", text))

    def add_assistant_response(
        self,
        text: str,
        tool_calls: list[ToolCall] | None = None,
        thought_signature: str | None = None,
    ) -> None:
        self.messages.append(RecordedMessage("assistant", text, tuple(tool_calls or ())))

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        self.messages.append(RecordedMessage("tool_result", result))


class ScriptedClient:
    """Mutable scripted provider that records each generation input."""

    def __init__(self, script: list[StreamResult]) -> None:
        self._script = script
        self._call_index = 0
        self.snapshots: list[tuple[RecordedMessage, ...]] = []

    def create_conversation(self, model: str = "") -> RecordingConversation:
        return RecordingConversation()

    async def stream_generate(
        self,
        *,
        conversation: RecordingConversation,
        model: str,
        system_instruction: str,
        tools: list[dict[str, JsonValue]],
    ) -> StreamResult:
        self.snapshots.append(tuple(conversation.messages))
        result = self._script[self._call_index]
        self._call_index += 1
        return result


@pytest.fixture
def isolated_chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    yield TestClient(sidecar.app)
    chat.set_client_builder(None)
    pending_approvals.revoke_all()


def _headers(**selection: str) -> dict[str, str]:
    headers = {"X-Session-Token": session_token.boot_token()}
    headers.update(selection)
    return headers


def _new_session(client: TestClient) -> str:
    response = client.post(
        "/api/chat/session", json={"title": "continuity"}, headers=_headers()
    )
    assert response.status_code == 200
    return str(response.json()["session_id"])


def _send(
    client: TestClient,
    session_id: str,
    message: str,
    **selection: str,
) -> Response:
    return client.post(
        "/api/chat",
        json={"session_id": session_id, "message": message},
        headers=_headers(**selection),
    )


@pytest.mark.parametrize(
    ("second_provider", "second_model"),
    [("provider-a", "model-a"), ("provider-b", "model-b")],
    ids=("same-selection", "provider-model-change"),
)
def test_second_turn_rehydrates_prior_context_before_new_user_message(
    isolated_chat: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    second_provider: str,
    second_model: str,
) -> None:
    # Given: a completed tool-backed turn in a durable Chat session.
    call = ToolCall(name="results_load", args={"path": "case.ppl"}, call_id="load-1")
    result = {"ok": True, "source": "case.ppl", "variables": ["PT", "TM"]}
    clients = [
        ScriptedClient(
            [
                StreamResult(tool_calls=[call]),
                StreamResult(text="The PT/TM result is ready."),
            ]
        ),
        ScriptedClient([StreamResult(text="I reused that result.")]),
    ]
    selections: list[tuple[str, str, str]] = []

    def resolve(
        headers: Mapping[str, str] | None, _settings: Mapping[str, JsonValue] | None
    ) -> tuple[str, str, str]:
        normalized = {key.casefold(): value for key, value in (headers or {}).items()}
        return normalized["x-llm-provider"], normalized["x-llm-model"], "medium"

    def build(provider: str, model: str, variant: str) -> ScriptedClient:
        selections.append((provider, model, variant))
        return clients.pop(0)

    monkeypatch.setattr(chat, "resolve_selection", resolve)
    monkeypatch.setattr(chat.runtime.tools, "dispatch", lambda _name, _args: result)
    chat.set_client_builder(build)
    session_id = _new_session(isolated_chat)
    first_selection = {"X-LLM-Provider": "provider-a", "X-LLM-Model": "model-a"}
    _send(isolated_chat, session_id, "Load PT and TM.", **first_selection)
    second_client = clients[0]

    # When: the follow-up refers to the prior tool-backed outcome.
    _send(
        isolated_chat,
        session_id,
        "Use that same result.",
        **{"X-LLM-Provider": second_provider, "X-LLM-Model": second_model},
    )

    # Then: canonical user, assistant, tool-call, and tool-result context precedes it.
    replay = second_client.snapshots[0]
    assert [message.kind for message in replay] == ["user", "assistant", "tool_result", "assistant", "user"]
    assert replay[0].text == "Load PT and TM."
    assert replay[1].tool_calls == (call,)
    assert json.loads(replay[2].text) == result
    assert replay[3].text == "The PT/TM result is ready."
    assert replay[4].text == "Use that same result."
    assert selections[-1] == (second_provider, second_model, "medium")


def test_exact_sanitized_tool_evidence_is_persisted_for_reload(
    isolated_chat: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: exact tool arguments and a result containing a nested credential.
    args = {"path": "case.ppl"}
    unsafe_result = {"ok": True, "metadata": {
        "source": "case.ppl", "authorization": "Bearer recursive-secret"
    }, "variables": ["PT", "TM"]}
    call = ToolCall(name="results_load", args=args, call_id="load-exact")
    chat.set_client_builder(
        lambda _p, _m, _v: ScriptedClient(
            [StreamResult(tool_calls=[call]), StreamResult(text="Loaded.")]
        )
    )
    monkeypatch.setattr(
        chat.runtime.tools, "dispatch", lambda _name, _args: unsafe_result
    )
    session_id = _new_session(isolated_chat)

    # When: the completed session is reloaded through the public history API.
    _send(isolated_chat, session_id, "Load the result.")
    response = isolated_chat.get(f"/api/chat/session/{session_id}")

    # Then: replayable evidence is exact while recursive credential material is absent.
    records = response.json()["records"]
    tool_call = next(record for record in records if record.get("type") == "tool_call")
    tool_result = next(
        record for record in records if record.get("type") == "tool_result"
    )
    assert tool_call.get("args") == args
    assert tool_result.get("result") == {"ok": True, "metadata": {
        "source": "case.ppl"
    }, "variables": ["PT", "TM"]}
    assert "recursive-secret" not in json.dumps(records)


def test_concurrent_turns_use_one_session_single_flight(
    isolated_chat: TestClient,
) -> None:
    # Given: a provider that holds the first request inside generation.
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    class BlockingClient(ScriptedClient):
        async def stream_generate(
            self,
            *,
            conversation: RecordingConversation,
            model: str,
            system_instruction: str,
            tools: list[dict[str, JsonValue]],
        ) -> StreamResult:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            entered.set()
            release.wait(timeout=5)
            with lock:
                active -= 1
            return StreamResult(text="completed")

    chat.set_client_builder(lambda _p, _m, _v: BlockingClient([]))
    session_id = _new_session(isolated_chat)

    def submit(message: str) -> None:
        _send(isolated_chat, session_id, message)

    # When: two requests target the same session before the first finishes.
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, "first")
        assert entered.wait(timeout=5)
        second = pool.submit(submit, "second")
        try:
            second.result(timeout=1)
        except TimeoutError:
            assert not second.done()
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)

    # Then: provider generation never overlaps for a session.
    assert maximum_active == 1


def test_session_delete_tombstones_history_without_cancelling_run(
    isolated_chat: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a session linked to an already-running simulation.
    session_id = _new_session(isolated_chat)
    history.append(
        session_id,
        {
            "record": "event",
            "type": "tool_result",
            "name": "run_execute",
            "result": {"run_id": "run-live", "state": "running"},
        },
    )
    cancelled: list[str] = []
    monkeypatch.setattr(runner, "cancel_run", lambda run_id: cancelled.append(run_id))

    # When: the user deletes/detaches the Chat session.
    response = isolated_chat.delete(
        f"/api/chat/session/{session_id}", headers=_headers()
    )

    # Then: history is tombstoned and hidden, while the simulation is untouched.
    assert response.status_code == 200
    assert cancelled == []
    session_path = history.chats_root() / f"{session_id}.jsonl"
    assert session_path.exists()
    assert history.read(session_id)[-1]["record"] == "tombstone"
    assert session_id not in {
        session["session_id"] for session in history.list_sessions()
    }


def test_a_late_record_from_an_in_flight_turn_does_not_resurrect_a_deleted_chat(
    isolated_chat: TestClient,
) -> None:
    # Given: a chat the user deleted while its turn was still producing records.
    session_id = _new_session(isolated_chat)
    isolated_chat.delete(f"/api/chat/session/{session_id}", headers=_headers())

    # When: the running turn finishes and writes its answer and an approval receipt.
    history.append(session_id, {"record": "assistant", "text": "late answer"})
    history.append(session_id, {"record": "terminal", "state": "completed"})

    # Then: the records are kept for audit, yet the chat stays hidden and cannot start a turn.
    records = history.read(session_id)
    assert [item["record"] for item in records if item["record"] in {"assistant", "terminal"}] == ["assistant", "terminal"]
    assert records[-1]["record"] == "tombstone"
    assert session_id not in {item["session_id"] for item in history.list_sessions()}
