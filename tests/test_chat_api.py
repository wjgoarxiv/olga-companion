"""T3 gate — chat API spine: session token, providers, SSE chat, history, mint route.

Offline: the provider client is replaced by a scripted FakeApiClient via the
chat.set_client_builder seam. No LLM, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
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
        self.calls = 0

    def create_conversation(self, model=""):
        return FakeConversation()

    async def stream_generate(self, **kwargs):
        r = self._script[self.calls]
        self.calls += 1
        return r


@pytest.fixture
def token():
    return session_token.boot_token()


@pytest.fixture(autouse=True)
def _reset_builder():
    yield
    chat.set_client_builder(None)
    pending_approvals.revoke_all()


# ---------------------------------------------------------------- session token

def test_session_token_endpoint_returns_boot_token(token):
    r = client.get("/api/session/token")
    assert r.status_code == 200
    assert r.json()["token"] == token


def test_approval_execute_requires_session_token():
    r = client.post(
        "/api/approvals/execute",
        json={"pending_id": "a" * 32, "session_id": "abc123abc123", "call_id": "c1", "context_generation": 0},
    )
    assert r.status_code == 401


def test_approval_execute_requires_a_nonnegative_strict_context_generation(token):
    headers = {"X-Session-Token": token}
    base = {"pending_id": "a" * 32, "session_id": "abc123abc123", "call_id": "c1"}

    assert client.post("/api/approvals/execute", json=base, headers=headers).status_code == 422
    assert client.post(
        "/api/approvals/execute", json={**base, "context_generation": -1}, headers=headers
    ).status_code == 422
    assert client.post(
        "/api/approvals/execute", json={**base, "context_generation": True}, headers=headers
    ).status_code == 422


def test_approval_mint_endpoint_is_not_exposed(token):
    response = client.post(
        "/api/approvals/mint",
        json={"action_kind": "run_execute", "payload": {"source": "/x"}, "context_generation": 0},
        headers={"X-Session-Token": token},
    )

    assert response.status_code == 404


def test_workspace_context_requires_valid_session_token(token):
    assert client.get("/api/workspace/context").status_code == 401
    assert client.get(
        "/api/workspace/context", headers={"X-Session-Token": "forged"}
    ).status_code == 401
    assert client.get(
        "/api/workspace/context", headers={"X-Session-Token": token}
    ).status_code == 200


def test_chat_requires_session_token():
    r = client.post("/api/chat", json={"session_id": "abc123abc123", "message": "hi"})
    assert r.status_code == 401


def test_run_execute_requires_session_token():
    """T3 review consistency fix: the direct run route is guarded like the chat spine."""
    r = client.post("/api/run/execute", json={"source": "/x.genkey", "approved": False})
    assert r.status_code == 401
    r2 = client.post("/api/run/cancel/deadbeef", json={})
    assert r2.status_code == 401


def test_sweep_execute_requires_session_token_and_plan_id(token):
    r = client.post("/api/sweep/execute", json={"sweep_id": "sweep-1", "approved": True})
    assert r.status_code == 401
    missing_plan = client.post(
        "/api/sweep/execute",
        json={"sweep_id": "sweep-1", "approved": True},
        headers={"X-Session-Token": token},
    )
    assert missing_plan.status_code == 400
    unknown_plan = client.post(
        "/api/sweep/execute",
        json={"sweep_id": "sweep-1", "plan_id": "plan-1", "approved": True},
        headers={"X-Session-Token": token},
    )
    assert unknown_plan.status_code == 404
    r2 = client.post("/api/sweep/cancel/sweep-1", json={})
    assert r2.status_code == 401


# ---------------------------------------------------------------- providers honesty

def test_providers_catalog_is_honest():
    r = client.get("/api/providers")
    assert r.status_code == 200
    body = r.json()["providers"]
    assert [p["provider"] for p in body] == ["openai", "copilot", "antigravity", "xai", "apikey"]
    by_name = {p["provider"]: p for p in body}
    assert "anthropic" not in by_name and "openrouter" not in by_name
    assert by_name["openai"]["known"] is True
    assert by_name["xai"]["login"] == "xai_device"
    assert by_name["apikey"]["login"] == "apikey"
    for name in ("openai", "copilot", "antigravity"):
        assert by_name[name]["login"] == "external"
    for item in body:
        assert isinstance(item["connected"], bool)


# ---------------------------------------------------------------- history

def test_chat_history_uses_per_test_root(tmp_path: Path):
    assert history.chats_root().is_relative_to(tmp_path)


def test_new_session_and_read(token):
    r = client.post("/api/chat/session", json={"title": "CO2 line"}, headers={"X-Session-Token": token})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    read = client.get(f"/api/chat/session/{sid}")
    assert read.status_code == 200
    recs = read.json()["records"]
    assert recs[0]["record"] == "meta"
    assert recs[0]["title"] == "CO2 line"


def test_read_unknown_session_404():
    r = client.get("/api/chat/session/deadbeefdeadbeef")
    assert r.status_code == 404


# ---------------------------------------------------------------- SSE chat

def _parse_sse(text):
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


def test_chat_streams_text_turn(token):
    chat.set_client_builder(lambda p, m, v: FakeApiClient([StreamResult(text="I can help with OLGA cases.")]))
    sid = client.post("/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}).json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "hi"}, headers={"X-Session-Token": token})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    types = [e[0] for e in events]
    assert types[0] == "open"
    assert "text" in types and "done" in types
    # History captured the turn.
    recs = client.get(f"/api/chat/session/{sid}").json()["records"]
    assert any(rec["record"] == "user" for rec in recs)
    assert any(rec["record"] == "assistant" for rec in recs)


def test_chat_streams_tool_turn(token):
    chat.set_client_builder(lambda p, m, v: FakeApiClient([
        StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
        StreamResult(text="An OLGA executable is available."),
    ]))
    sid = client.post("/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}).json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "is olga installed?"}, headers={"X-Session-Token": token})
    events = _parse_sse(r.text)
    types = [e[0] for e in events]
    assert "tool_call" in types and "tool_result" in types and "done" in types


def test_approval_executes_server_stored_action_without_exposing_token(
    token, monkeypatch: pytest.MonkeyPatch, tmp_path
):
    from olga_companion import workspace

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    dispatched: list[tuple[str, dict]] = []
    chat.set_client_builder(lambda p, m, v: FakeApiClient([
        StreamResult(tool_calls=[ToolCall(
            name="run_execute",
            args={"source": str(case), "timeout_s": 3600, "selection_id": "selection-1"},
            call_id="call-1",
        )]),
    ]))
    monkeypatch.setattr(
        "olga_companion.sidecar.tools.dispatch",
        lambda name, args: dispatched.append((name, args)) or {"run_id": "run-1", "state": "running"},
    )
    # This test is about the approval lifecycle, not runtime detection: without a stub the
    # card's preview would probe the host's installed OLGA and build the native broker.
    monkeypatch.setattr(
        "olga_companion.agent.tools.approval_display",
        lambda _name, _args, locale="ko": {
            "case": case.name,
            "selection_id": "selection-1",
        },
    )
    sid = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]

    streamed = client.post(
        "/api/chat", json={"session_id": sid, "message": "run it"}, headers={"X-Session-Token": token}
    )
    events = _parse_sse(streamed.text)
    approval = next(data for event, data in events if event == "approval_required")
    assert isinstance(approval["pending_id"], str)
    assert "approval_token" not in streamed.text

    executed = client.post(
        "/api/approvals/execute",
        json={
            "pending_id": approval["pending_id"],
            "session_id": sid,
            "call_id": "call-1",
            "context_generation": workspace.context_generation(),
        },
        headers={"X-Session-Token": token},
    )

    assert executed.status_code == 200
    assert executed.json() == {
        "name": "run_execute",
        "call_id": "call-1",
        "result": {"run_id": "run-1", "state": "running"},
        "state": "resume_pending",
        "resume_allowed": True,
    }
    assert dispatched[0][0] == "run_execute"
    assert isinstance(dispatched[0][1].get("approval_token"), str)
    assert "approval_token" not in executed.text
    assert client.post(
        "/api/approvals/execute",
        json={
            "pending_id": approval["pending_id"],
            "session_id": sid,
            "call_id": "call-1",
            "context_generation": workspace.context_generation(),
        },
        headers={"X-Session-Token": token},
    ).json() == executed.json()
    assert len(dispatched) == 1
    history_payload = client.get(f"/api/chat/session/{sid}").text
    assert "approval_token" not in history_payload


def test_chat_unconnected_provider_streams_error(token):
    chat.set_client_builder(lambda p, m, v: None)  # no creds
    sid = client.post("/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}).json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "hi"}, headers={"X-Session-Token": token})
    events = _parse_sse(r.text)
    assert any(e[0] == "error" for e in events)


def test_chat_provider_exception_is_redacted_from_sse(token):
    secret = "Bearer top-secret-token /private/customer/case.genkey"

    class ExplodingClient(FakeApiClient):
        async def stream_generate(self, **kwargs):
            raise RuntimeError(secret)

    chat.set_client_builder(lambda p, m, v: ExplodingClient([]))
    sid = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]

    response = client.post(
        "/api/chat",
        json={"session_id": sid, "message": "hi"},
        headers={"X-Session-Token": token},
    )
    events = _parse_sse(response.text)
    error = next(data for event, data in events if event == "error")

    assert secret not in response.text
    assert "top-secret-token" not in error["message"]
    assert error["message"] == "응답을 만들지 못했습니다. 공급자 연결을 확인하고 다시 시도하세요."


def test_no_credential_material_persisted(token):
    chat.set_client_builder(lambda p, m, v: FakeApiClient([StreamResult(text="ok")]))
    sid = client.post("/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}).json()["session_id"]
    client.post("/api/chat", json={"session_id": sid, "message": "hi"}, headers={"X-Session-Token": token})
    raw = json.dumps(client.get(f"/api/chat/session/{sid}").json())
    for banned in ("access_token", "refresh_token", "Bearer ", "api_key"):
        assert banned not in raw
