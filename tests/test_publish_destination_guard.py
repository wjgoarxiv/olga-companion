"""A destination whose parent is missing is refused before a human is asked."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from case_spec_v2_support import PVT_TABLE_TEXT, with_v2_inputs
from olga_companion import workspace
from olga_companion.agent import (
    approval_execution,
    chat,
    history,
    pending_approvals,
    runtime,
    session_token,
    tools,
)
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.llm.protocol import StreamResult, ToolCall
from olga_companion.sidecar import app

RECOVERY = (
    "저장 위치는 워크스페이스 루트 안의 기존 폴더여야 합니다. "
    "현재 케이스 옆에 저장하려면 그 케이스의 워크스페이스 상대 폴더를 유지한 채 새 파일 이름을 붙이세요."
)
DESTINATION_RULE = (
    "destination_rel is relative to the workspace root. "
    "To save beside the active case, use the active case's workspace-relative folder "
    "plus the new file name. Use only the file name when the active case sits directly in the root."
)
FALSE_ROOT_CLAIM = "folder that contains the active case"
client = TestClient(app)


class _Conversation:
    def add_user_message(self, text, images=None): ...
    def add_assistant_response(self, text, tool_calls=None, thought_signature=None): ...
    def add_tool_result(self, call_id, name, result): ...


class _Client:
    def __init__(self, script):
        self._script = list(script)

    def create_conversation(self, model=""):
        return _Conversation()

    async def stream_generate(self, **kwargs):
        return self._script.pop(0)


def _spec() -> dict:
    return with_v2_inputs({
        "nodes": [
            {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "SINK", "kind": "sink", "pressure_pa": 1_000_000.0},
        ],
        "flowpaths": [{
            "label": "MAIN",
            "from": "SOURCE",
            "to": "SINK",
            "pipes": [{
                "label": "PIPE_1",
                "centerline_m": [[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
                "diameter_m": 0.1,
                "sections": 10,
            }],
        }],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT"],
    })


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "simulation"
    root.mkdir()
    (root / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    (root / "current.genkey").write_text("CASE\n", encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    workspace.set_active_rel("current.genkey")
    return root


def _plan(root: Path, destination: str) -> dict:
    spec = _spec()
    validated = tools.dispatch("case_spec_validate", {"spec": spec})
    assert validated["valid"] is True
    return tools.dispatch(
        "case_edit_plan",
        {
            "spec": spec,
            "spec_hash": validated["spec_hash"],
            "destination_rel": destination,
            "operations": [],
        },
    )


@pytest.fixture(autouse=True)
def _clear() -> None:
    pending_approvals.revoke_all()
    yield
    chat.set_client_builder(None)
    pending_approvals.revoke_all()


def test_prompt_and_tool_schema_keep_destination_relative_to_the_workspace_root() -> None:
    assert FALSE_ROOT_CLAIM not in SYSTEM_PROMPT
    assert DESTINATION_RULE in SYSTEM_PROMPT
    specs = {item["name"]: item for item in tools.tool_specs()}
    for name in ("case_edit_plan", "case_publish"):
        text = json.dumps(specs[name])
        assert FALSE_ROOT_CLAIM not in text
        assert DESTINATION_RULE in text
    recovery = approval_execution._PUBLISH_RECOVERY["unsafe_destination"]
    assert recovery == RECOVERY
    assert "파일 이름만" not in recovery


def test_nested_active_case_keeps_its_folder_in_the_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "DEMO"
    case_dir = root / "simulation"
    case_dir.mkdir(parents=True)
    (root / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    (case_dir / "current.genkey").write_text("CASE\n", encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    workspace.set_active_rel("simulation/current.genkey")

    beside = _plan(root, "simulation/new.genkey")
    assert beside["publishable"] is True
    at_root = _plan(root, "new.genkey")
    assert at_root["publishable"] is True
    resolved = workspace.contained("new.genkey")
    assert resolved.parent == root.resolve()

    seen: list[str] = []

    class _Recording:
        def create_conversation(self, model=""):
            return _Conversation()

        async def stream_generate(self, **kwargs):
            seen.append(kwargs["system_instruction"])
            return StreamResult(text="noted")

    async def _turn() -> None:
        async for _event in runtime.run_turn(_Recording(), "같은 폴더에 저장"):
            pass

    asyncio.run(_turn())
    assert seen
    assert "simulation/current.genkey" in seen[0]
    assert FALSE_ROOT_CLAIM not in seen[0]


def test_nested_destination_is_refused_while_planning_a_new_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, monkeypatch)

    with pytest.raises(tools.ToolError, match="unsafe_destination"):
        _plan(root, "simulation/x.genkey")

    assert not (root / "simulation").exists()
    assert pending_approvals.session_has_pending("unused") is False


def test_nested_destination_does_not_create_an_approval_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, monkeypatch)
    plan = _plan(root, "x.genkey")
    assert plan["publishable"] is True
    chat.set_client_builder(lambda _p, _m, _v: _Client([
        StreamResult(tool_calls=[ToolCall(
            name="case_publish",
            args={
                "transaction_id": plan["transaction_id"],
                "source_hash": plan["source_hash"],
                "compiled_hash": plan["compiled_hash"],
                "destination_rel": "simulation/x.genkey",
                "context_generation": plan["context_generation"],
            },
            call_id="publish-1",
        )]),
        StreamResult(text="The destination was refused."),
    ]))
    token = session_token.boot_token()
    session_id = client.post(
        "/api/chat/session", json={"title": ""}, headers={"X-Session-Token": token}
    ).json()["session_id"]

    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "저장해 주세요"},
        headers={"X-Session-Token": token},
    )

    body = response.text
    assert "approval_required" not in body
    assert "unsafe_destination" in body
    assert pending_approvals.session_has_pending(session_id) is False
    assert not (root / "simulation").exists()


def test_approved_publish_of_a_missing_parent_is_refused_not_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, monkeypatch)
    plan = _plan(root, "x.genkey")
    session_id = history.new_session("destination")
    generation = plan["context_generation"]
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={
            "transaction_id": plan["transaction_id"],
            "source_hash": plan["source_hash"],
            "compiled_hash": plan["compiled_hash"],
            "destination_rel": "simulation/x.genkey",
            "context_generation": generation,
        },
        call_id="publish-late",
        context_generation=generation,
        session_id=session_id,
    )

    executed = approval_execution.execute(
        pending_id=pending_id,
        session_id=session_id,
        call_id="publish-late",
        context_generation=generation,
    )

    assert executed["state"] == "failed"
    assert executed["result"]["code"] == "unsafe_destination"
    assert executed["result"]["error"] == f"unsafe_destination: {RECOVERY}"
    assert "uncertain" not in json.dumps(executed)
    assert pending_approvals.session_has_pending(session_id) is False
    assert not (root / "simulation" / "x.genkey").exists()
