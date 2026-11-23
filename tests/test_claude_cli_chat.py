"""The local CLI inside the real chat routes: SSE, history, approval card, click, continuation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import bridge_registry, starter_fluids
from olga_companion.agent import chat, history, pending_approvals, session_token
from olga_companion.llm import claude_cli_client, claude_cli_discovery, claude_cli_launch, provider_runtime_status
from olga_companion.sidecar import app
from olga_companion.sidecar_bridge_routes import DATA_CLOSE

CLI = Path(__file__).parent / "fixtures" / "claude_cli"
FLUIDS = Path(__file__).parent / "fixtures" / "fluids"
INIT = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "claude_code_version": "2.1.220"}
RESULT_OK = {"type": "result", "subtype": "success", "is_error": False, "result": "저장했습니다."}


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "workspace"
    root.mkdir()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    stand_in = (FLUIDS / "standard_three.tab").read_text(encoding="utf-8").replace("FLUID-A", "AIR_WATER")
    (bundle / starter_fluids.TABLE_NAME).write_text(stand_in, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(starter_fluids, "bundled_table", lambda: bundle / starter_fluids.TABLE_NAME)
    monkeypatch.setattr(bridge_registry, "_path", lambda: tmp_path / "bridge-connections.json")
    monkeypatch.setattr(claude_cli_launch, "run_root", lambda: tmp_path / "runs")
    monkeypatch.setattr(claude_cli_launch, "harden_private_path", lambda _p, directory: None)
    found = claude_cli_discovery.CliResolution("ok", [sys.executable, str(CLI / "fake_claude.py")], "x", "2.1.220")
    chat.set_client_builder(lambda _p, m, _v: claude_cli_client.ClaudeCliClient(model=m or "default",
                                                                                  resolve=lambda: found))
    pending_approvals.revoke_all()
    provider_runtime_status.reset_all()
    session_token.boot_token()
    yield root
    chat.set_client_builder(None)
    pending_approvals.revoke_all()
    provider_runtime_status.reset_all()


def _scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **keys) -> None:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(keys), encoding="utf-8")
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(path))


def _sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        kind = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if kind:
            events.append((kind, data))
    return events


def _api() -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8865", client=("127.0.0.1", 50000))


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _turn(message: str) -> tuple[str, list[tuple[str, dict]]]:
    api = _api()
    session_id = api.post("/api/chat/session", json={"title": ""}, headers=_headers()).json()["session_id"]
    response = api.post("/api/chat", json={"session_id": session_id, "message": message}, headers=_headers())
    assert response.status_code == 200, response.text
    return session_id, _sse(response.text)


def test_a_read_turn_lands_in_the_usual_sse_and_history_shapes(tmp_path, monkeypatch):
    _scenario(tmp_path, monkeypatch, replay=str(CLI / "tool_read.jsonl"))
    session_id, events = _turn("에코 해 줘")
    kinds = [k for k, _ in events if k in ("tool_call", "tool_result", "text", "done", "error")]
    assert kinds[-1] == "done" and "tool_call" in kinds and "tool_result" in kinds
    records = history.read(session_id)
    tags = [(r.get("record"), r.get("type")) for r in records]
    assert ("assistant", None) in tags and ("event", "tool_call") in tags and ("event", "tool_result") in tags
    assert tags[-1] == ("terminal", None)
    assistant_calls = [r for r in records if r.get("record") == "assistant" and r.get("tool_calls")]
    assert assistant_calls[0]["tool_calls"][0]["name"] == "probe_echo"


def test_a_write_request_becomes_a_card_and_approval_continues_with_the_result(tmp_path, monkeypatch, _isolated):
    target = _isolated / "air_water.tab"
    ask = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "공기-물 표를 만들겠습니다."},
        {"type": "tool_use", "id": "toolu_w", "name": "mcp__olga-companion__fluids_starter_tab",
         "input": {"tab_rel": "air_water.tab"}}]}}
    _scenario(tmp_path, monkeypatch, lines=[INIT, ask], sleep=60)
    session_id, events = _turn("공기-물 표를 만들어 줘")
    card = next(data for kind, data in events if kind == "approval_required")
    assert card["name"] == "fluids_starter_tab" and card["pending_id"]
    assert not target.exists()

    identity = {"pending_id": card["pending_id"], "session_id": session_id, "call_id": card["call_id"],
                "context_generation": card["context_generation"]}
    api = _api()
    executed = api.post("/api/approvals/execute", json=identity, headers=_headers())
    assert executed.status_code == 200, executed.text
    assert target.is_file()

    capture = tmp_path / "continuation.json"
    _scenario(tmp_path, monkeypatch, capture=str(capture),
              lines=[INIT, {"type": "assistant", "message": {"content": [{"type": "text", "text": "저장했습니다."}]}},
                     RESULT_OK])
    resumed = api.post("/api/approvals/resume", json=identity, headers=_headers())
    assert resumed.status_code == 200
    done = [data for kind, data in _sse(resumed.text) if kind == "done"]
    assert done and done[-1]["text"] == "저장했습니다."
    prompt = json.loads(capture.read_text(encoding="utf-8"))["stdin"]
    assert prompt.rstrip().endswith(DATA_CLOSE)
    assert "fluids_starter_tab" in prompt.rsplit("### Tool result", 1)[1]
    assert prompt.count("공기-물 표를 만들어 줘") == 1


def test_without_a_cli_the_usual_not_connected_message_appears(tmp_path, monkeypatch):
    from olga_companion import config

    monkeypatch.setattr(config, "llm_selection_path", lambda: tmp_path / "llm-selection.json")
    chat.set_client_builder(lambda _p, _m, _v: None)
    saved = _api().put("/api/llm-selection", json={"provider": "claude_cli", "model": "default", "variant": "medium"},
                       headers=_headers())
    assert saved.status_code == 200, saved.text
    _, events = _turn("안녕")
    error = next(data for kind, data in events if kind == "error")
    assert "연결되어 있지 않습니다" in error["message"]
    assert "이 PC의 로컬 CLI" in error["message"] and "Local CLI" not in error["message"]


def test_not_signed_in_is_shown_in_korean_and_marks_the_provider(tmp_path, monkeypatch):
    _scenario(tmp_path, monkeypatch, replay=str(CLI / "not_logged_in.jsonl"), exit=1)
    _, events = _turn("안녕")
    error = next(data for kind, data in events if kind == "error")
    assert "로그인되어 있지 않습니다" in error["message"]
    assert provider_runtime_status.failed("claude_cli")


def test_the_real_builder_returns_none_when_no_cli_is_found(monkeypatch):
    def blocking(**_kw):
        raise AssertionError("the builder runs on the event loop and must not probe the CLI")

    monkeypatch.setattr(claude_cli_discovery, "resolve", blocking)
    monkeypatch.setattr(claude_cli_discovery, "peek", lambda: claude_cli_discovery.CliResolution("not_installed"))
    assert chat._build_real_client("claude_cli", "default", "medium") is None
    found = claude_cli_discovery.CliResolution("ok", ["x"], "x", "2.1.220")
    monkeypatch.setattr(claude_cli_discovery, "peek", lambda: found)
    assert isinstance(chat._build_real_client("claude_cli", "sonnet", "medium"), claude_cli_client.ClaudeCliClient)
    monkeypatch.setattr(claude_cli_discovery, "peek", lambda: None)
    assert isinstance(chat._build_real_client("claude_cli", "default", "medium"), claude_cli_client.ClaudeCliClient)
