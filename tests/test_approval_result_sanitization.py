from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from olga_companion import config, workspace
from olga_companion.agent import (
    approval_execution,
    approval_journal,
    chat,
    history,
    pending_approvals,
)
from olga_companion.llm.protocol import StreamResult


class RecordingConversation:
    def __init__(self) -> None:
        self.tool_results: list[str] = []

    def add_user_message(self, _text: str, _images=None) -> None:
        return None

    def add_assistant_response(
        self, _text: str, _tool_calls=None, _thought_signature=None
    ) -> None:
        return None

    def add_tool_result(self, _call_id: str, _name: str, result: str) -> None:
        self.tool_results.append(result)


class RecordingClient:
    def __init__(self) -> None:
        self.conversation = RecordingConversation()

    def create_conversation(self, _model: str = "") -> RecordingConversation:
        return self.conversation

    async def stream_generate(self, **_kwargs) -> StreamResult:
        return StreamResult(text="Approved action completed.")


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv(
        "OLGA_APPROVAL_JOURNAL_DIR", str(tmp_path / "approval-journal")
    )
    monkeypatch.setattr(config, "project_root", lambda: tmp_path)
    pending_approvals.revoke_all()
    chat.set_client_builder(None)
    yield
    pending_approvals.revoke_all()
    chat.set_client_builder(None)


def _unsafe_result() -> dict:
    return {
        "ok": True,
        "authorization": "Bearer probe-secret",
        "accessKey": "credential-alias-secret",
        "paths": {
            "wsl": "/home/private/result.out",
            "windows": r"C:\Users\Woojin\private\result.out",
        },
        "values": list(range(200)),
        "nested": {"log": "x" * 20_000},
    }


def _assert_canonical(result: dict) -> None:
    encoded = json.dumps(result)
    assert result["ok"] is True
    assert "authorization" not in result
    assert "accessKey" not in result
    assert result["paths"]["wsl"].startswith("path-sha256:")
    assert result["paths"]["windows"].startswith("path-sha256:")
    assert len(result["values"]) == 128
    assert len(result["nested"]["log"]) == 16_384
    assert "probe-secret" not in encoded
    assert "/home/private" not in encoded
    assert "C:\\\\Users" not in encoded


def test_complete_sanitizes_before_terminal_journal_commit() -> None:
    # Given: a claimed approval and an unsafe dispatch result.
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={},
        call_id="call-unit",
        context_generation=0,
        session_id="abc123abc123",
    )
    approval = pending_approvals.claim(
        pending_id,
        session_id="abc123abc123",
        call_id="call-unit",
        context_generation=0,
    )

    # When: the action becomes terminal.
    completed = pending_approvals.complete(pending_id, approval, _unsafe_result())

    # Then: memory and durable journal share one bounded canonical value.
    journal_result = approval_journal.load_all()[pending_id]["result"]
    _assert_canonical(completed.result)
    assert journal_result == completed.result


def test_execute_replay_and_resume_share_canonical_terminal_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: one approval whose dispatch returns credentials, private paths, and oversize data.
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    session_id = history.new_session("sanitized approval")
    generation = workspace.context_generation()
    call_id = "call-sanitized"
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": str(case), "timeout_s": 3600, "selection_id": "selection-1"},
        call_id=call_id,
        context_generation=generation,
        session_id=session_id,
    )
    history.append(
        session_id,
        {
            "record": "approval",
            "pending_id": pending_id,
            "name": "run_execute",
            "call_id": call_id,
            "state": "pending",
            "provider": "openai",
            "model": "probe-model",
        },
    )
    monkeypatch.setattr(approval_execution.tools, "dispatch", lambda _n, _a: _unsafe_result())
    client = RecordingClient()
    chat.set_client_builder(lambda _p, _m, _v: client)
    identity = {
        "pending_id": pending_id,
        "session_id": session_id,
        "call_id": call_id,
        "context_generation": generation,
    }

    # When: execute, replay, and provider continuation consume the receipt.
    executed = approval_execution.execute(**identity)
    replayed = approval_execution.execute(**identity)
    resumed = anyio.run(lambda: approval_execution.resume(**identity))

    # Then: every surface observes the exact same sanitized result.
    canonical = executed["result"]
    _assert_canonical(canonical)
    assert replayed["result"] == canonical
    assert resumed["result"] == canonical
    assert json.loads(client.conversation.tool_results[-1]) == canonical
    journal_result = approval_journal.load_all()[pending_id]["result"]
    assert journal_result == canonical
    tool_results = [
        record["result"]
        for record in history.read(session_id)
        if record.get("type") == "tool_result"
    ]
    assert tool_results[-1] == canonical
