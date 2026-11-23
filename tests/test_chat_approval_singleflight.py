"""Approval dispatch shares the Chat session single-flight lease."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

import pytest
from fastapi.testclient import TestClient

from olga_companion import sidecar, workspace
from olga_companion.agent import chat, history, pending_approvals, session_token
from olga_companion.llm.protocol import StreamResult


class DispatchResult(TypedDict):
    run_id: str
    state: str


class EmptyConversation:
    def add_user_message(self, text: str, images: list[bytes] | None = None) -> None:
        return

    def add_assistant_response(
        self, text: str, tool_calls=None, thought_signature=None
    ) -> None:
        return

    def add_tool_result(self, call_id: str, name: str, result: str) -> None:
        return


class EntryClient:
    def __init__(self, entered: threading.Event) -> None:
        self._entered = entered

    def create_conversation(self, model: str = "") -> EmptyConversation:
        return EmptyConversation()

    async def stream_generate(self, **_kwargs) -> StreamResult:
        self._entered.set()
        return StreamResult(text="chat completed")


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def test_approval_dispatch_and_user_turn_cannot_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an approved dispatch paused inside the shared session boundary.
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    session_id = history.new_session("approval lock")
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": str(case), "timeout_s": 3600, "selection_id": "selection-1"},
        call_id="call-lock",
        context_generation=generation,
        session_id=session_id,
    )
    expected_envelope = {
        "turn_id": "turn-approval",
        "request_id": "request-approval",
        "workspace_root": "path-sha256:approval-root",
        "provider": "openai",
        "model": "gpt-5.6-terra",
    }
    history.append(
        session_id,
        {
            "record": "approval",
            "pending_id": pending_id,
            "call_id": "call-lock",
            "state": "pending",
            **expected_envelope,
        },
    )
    history.append(
        session_id,
        {
            "record": "approval",
            "pending_id": "decoy-pending-id",
            "state": "pending",
            "turn_id": "wrong-turn",
            "request_id": "wrong-request",
            "workspace_root": "path-sha256:wrong-root",
            "provider": "wrong-provider",
            "model": "wrong-model",
        },
    )
    dispatch_entered = threading.Event()
    release_dispatch = threading.Event()
    chat_entered = threading.Event()

    def blocking_dispatch(_name: str, _args: dict) -> DispatchResult:
        dispatch_entered.set()
        assert release_dispatch.wait(timeout=5)
        return {"run_id": "run-lock", "state": "running"}

    monkeypatch.setattr(sidecar.tools, "dispatch", blocking_dispatch)
    chat.set_client_builder(lambda _p, _m, _v: EntryClient(chat_entered))
    api = TestClient(sidecar.app)
    approval_payload = {
        "pending_id": pending_id,
        "session_id": session_id,
        "call_id": "call-lock",
        "context_generation": generation,
    }

    # When: a user turn targets the session while approval dispatch is in flight.
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(
                api.post,
                "/api/approvals/execute",
                json=approval_payload,
                headers=_headers(),
            )
            assert dispatch_entered.wait(timeout=5)
            user_turn = pool.submit(
                api.post,
                "/api/chat",
                json={"session_id": session_id, "message": "What happened?"},
                headers=_headers(),
            )
            assert not chat_entered.wait(timeout=0.5)
            release_dispatch.set()
            assert approval.result(timeout=5).status_code == 200
            assert user_turn.result(timeout=5).status_code == 200
    finally:
        release_dispatch.set()
        chat.set_client_builder(None)
        pending_approvals.revoke_all()

    # Then: the dispatch receipt is durable but remains finalizing until resume.
    assert chat_entered.is_set()
    completed = next(
        record
        for record in history.read(session_id)
        if record.get("record") == "approval"
        and record.get("state") == "resume_pending"
    )
    assert completed["pending_id"] == pending_id
    assert completed["call_id"] == "call-lock"
    assert completed["result"] == {"run_id": "run-lock", "state": "running"}
    assert completed["lifecycle"] == "finalizing"
    assert completed["resume_allowed"] is True
    for key, value in expected_envelope.items():
        assert completed[key] == value
    assert "approval_token" not in str(completed)
