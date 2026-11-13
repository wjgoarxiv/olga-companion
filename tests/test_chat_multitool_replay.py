"""Canonical multi-tool assistant replay across sidecar lifecycles."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from olga_companion import sidecar
from olga_companion.agent import chat, history, session_token
from olga_companion.llm.protocol import StreamResult, ToolCall


@dataclass(frozen=True, slots=True)
class RecordedMessage:
    kind: Literal["user", "assistant", "tool_result"]
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    thought_signature: str | None = None


class RecordingConversation:
    """Mutable fake implementing the provider conversation protocol."""

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
        self.messages.append(
            RecordedMessage(
                "assistant", text, tuple(tool_calls or ()), thought_signature
            )
        )

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        self.messages.append(RecordedMessage("tool_result", result))


class ScriptedClient:
    def __init__(self, script: list[StreamResult]) -> None:
        self._script = script
        self._index = 0
        self.snapshots: list[tuple[RecordedMessage, ...]] = []

    def create_conversation(self, model: str = "") -> RecordingConversation:
        return RecordingConversation()

    async def stream_generate(
        self,
        *,
        conversation: RecordingConversation,
        model: str,
        system_instruction: str,
        tools: list[dict],
    ) -> StreamResult:
        self.snapshots.append(tuple(conversation.messages))
        result = self._script[self._index]
        self._index += 1
        return result


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def test_multi_tool_assistant_replays_once_with_ordered_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: one provider response containing two native tool calls and opaque fields.
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    first_call = ToolCall(
        name="results_load",
        args={"path": "case.ppl"},
        call_id="load-1",
        raw_arguments='{"api_key":"provider-secret","path":"case.ppl"}',
        item_id="item-load",
    )
    second_call = ToolCall(
        name="run_detect",
        args={},
        call_id="detect-1",
        raw_arguments="{}",
        item_id="item-detect",
    )
    first_client = ScriptedClient(
        [
            StreamResult(
                thinking="hidden reasoning must not persist",
                tool_calls=[first_call, second_call],
                thought_signature="opaque-provider-signature",
            ),
            StreamResult(text="Both tools completed."),
        ]
    )
    second_client = ScriptedClient([StreamResult(text="I reused both results.")])
    clients = [first_client, second_client]
    chat.set_client_builder(lambda _p, _m, _v: clients.pop(0))
    monkeypatch.setattr(
        chat.runtime.tools,
        "dispatch",
        lambda name, _args: {"tool": name, "ok": True},
    )

    # When: one turn completes, the app client is recreated, and a follow-up runs.
    try:
        with TestClient(sidecar.app) as first_api:
            session_id = first_api.post(
                "/api/chat/session", json={"title": "multi"}, headers=_headers()
            ).json()["session_id"]
            first_api.post(
                "/api/chat",
                json={"session_id": session_id, "message": "Use both tools."},
                headers=_headers(),
            )
        with TestClient(sidecar.app) as restarted_api:
            restarted_api.post(
                "/api/chat",
                json={"session_id": session_id, "message": "Use those results."},
                headers=_headers(),
            )
    finally:
        chat.set_client_builder(None)

    # Then: exactly one assistant message carries both calls before ordered results.
    snapshot = second_client.snapshots[0]
    tool_assistants = [
        message
        for message in snapshot
        if message.kind == "assistant" and message.tool_calls
    ]
    assert len(tool_assistants) == 1
    replayed_first, replayed_second = tool_assistants[0].tool_calls
    assert replayed_first == ToolCall(
        name="results_load",
        args={"path": "case.ppl"},
        call_id="load-1",
        raw_arguments='{"path":"case.ppl"}',
        item_id="item-load",
    )
    assert replayed_second == second_call
    assert tool_assistants[0].thought_signature == "opaque-provider-signature"
    results = [json.loads(message.text) for message in snapshot if message.kind == "tool_result"]
    assert results == [
        {"tool": "results_load", "ok": True},
        {"tool": "run_detect", "ok": True},
    ]
    records = history.read(str(session_id))
    batch = next(record for record in records if record.get("tool_calls"))
    assert [call["call_id"] for call in batch["tool_calls"]] == ["load-1", "detect-1"]
    assert batch["thought_signature"] == "opaque-provider-signature"
    assert records[1]["workspace_root"].startswith("path-sha256:")
    assert "hidden reasoning" not in json.dumps(records)


class _BuilderClient:
    """Wraps one real provider conversation builder; no network."""

    def __init__(self, conversation):
        self._conversation = conversation

    def create_conversation(self, model: str = ""):
        return self._conversation


def _payload_calls_and_results(kind: str, payload: list[dict]) -> tuple[set[str], set[str]]:
    if kind == "chat":
        calls = {
            call["id"]
            for message in payload
            if message.get("role") == "assistant"
            for call in message.get("tool_calls", [])
        }
        results = {
            message.get("tool_call_id")
            for message in payload
            if message.get("role") == "tool"
        }
        return calls, results
    if kind == "responses":
        calls = {
            item.get("call_id")
            for item in payload
            if item.get("type") == "function_call"
        }
        results = {
            item.get("call_id")
            for item in payload
            if item.get("type") == "function_call_output"
        }
        return calls, results
    assert kind == "antigravity"
    calls = {
        part["functionCall"].get("id", part["functionCall"].get("name"))
        for message in payload
        for part in message.get("parts", [])
        if "functionCall" in part
    }
    answered = any(
        "functionResponse" in part
        for message in payload
        for part in message.get("parts", [])
    )
    return calls, calls if answered else set()


@pytest.mark.parametrize("ending", ["rejected", "failed"])
def test_replay_after_failed_or_rejected_approval_has_no_orphan_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    from olga_companion import fluid_table, workspace
    from olga_companion.agent import (
        approval_execution,
        chat_replay,
        history,
        pending_approvals,
    )
    from olga_companion.llm.antigravity_adapter import AntigravityConversationBuilder
    from olga_companion.llm.openai_chat_adapter import OpenAIChatConversationBuilder
    from olga_companion.llm.openai_responses_adapter import (
        OpenAIResponsesConversationBuilder,
    )

    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        fluid_table, "databank_names", lambda *args, **kwargs: {"METHANE": "METHANE"}
    )
    pending_approvals.revoke_all()
    try:
        session_id = history.new_session("orphan-probe")
        _root, generation = workspace.context_identity()
        args = {
            "fluid_label": "SYN1",
            "components": [{"name": "METHANE", "mole_fraction": 1.0}],
            "model": "SRK",
            "temperatures": [-10.0, 50.0],
            "temperature_unit": "degC",
            "pressures": [0.0, 5.0],
            "pressure_unit": "barg",
            "mfl_rel": "synthetic.mfl",
        }
        common = {"workspace_generation": generation, "provider": "p", "model": "m"}
        history.append(session_id, {"record": "user", "text": "draft it", **common})
        history.append(
            session_id,
            {
                "record": "assistant",
                "text": "",
                "tool_calls": [{"name": "fluids_draft_mfl", "args": args, "call_id": "orphan-1", "raw_arguments": "{}", "item_id": ""}],
                **common,
            },
        )
        history.append(
            session_id,
            {
                "record": "event",
                "type": "tool_call",
                "name": "fluids_draft_mfl",
                "call_id": "orphan-1",
                "args": args,
                "raw_arguments": "{}",
                "item_id": "",
                **common,
            },
        )
        pending_id = pending_approvals.register(
            action_kind="fluids_draft_mfl",
            args=dict(args),
            call_id="orphan-1",
            context_generation=generation,
            session_id=session_id,
        )
        history.append(
            session_id,
            {
                "record": "approval",
                "pending_id": pending_id,
                "call_id": "orphan-1",
                "name": "fluids_draft_mfl",
                "args": args,
                "state": "pending",
                **common,
            },
        )
        if ending == "rejected":
            approval_execution.reject(
                pending_id=pending_id,
                session_id=session_id,
                call_id="orphan-1",
                context_generation=generation,
            )
        else:
            monkeypatch.setattr(
                fluid_table,
                "databank_names",
                lambda *args, **kwargs: {"METHANE": "METHANE"},
            )
            bad = dict(args)
            bad["pressure_unit"] = "furlong"
            pending_approvals.revoke_all()
            pending_id = pending_approvals.register(
                action_kind="fluids_draft_mfl",
                args=bad,
                call_id="orphan-1",
                context_generation=generation,
                session_id=session_id,
            )
            history.append(
                session_id,
                {
                    "record": "approval",
                    "pending_id": pending_id,
                    "call_id": "orphan-1",
                    "name": "fluids_draft_mfl",
                    "args": bad,
                    "state": "pending",
                    **common,
                },
            )
            body = approval_execution.execute(
                pending_id=pending_id,
                session_id=session_id,
                call_id="orphan-1",
                context_generation=generation,
            )
            assert body["state"] == "failed"

        records = history.read(session_id)
        builders = {
            "chat": OpenAIChatConversationBuilder(),
            "responses": OpenAIResponsesConversationBuilder(),
            "antigravity": AntigravityConversationBuilder(model="gemini-test"),
        }
        for kind, builder in builders.items():
            conversation = chat_replay.rebuild_conversation(
                _BuilderClient(builder), "probe-model", records
            )
            calls, results = _payload_calls_and_results(
                kind, conversation.get_request_payload()
            )
            assert calls, f"{kind} builder dropped the refused call entirely"
            assert calls <= results, (
                f"{kind} builder replays an orphan tool call: {calls - results}"
            )
    finally:
        pending_approvals.revoke_all()
    raw_history = (
        history.chats_root() / f"{session_id}.jsonl"
    ).read_text(encoding="utf-8")
    assert "provider-secret" not in raw_history
    assert "api_key" not in raw_history
