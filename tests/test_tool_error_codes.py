"""A failed tool result carries a stable machine code beside its English text.

The UI maps the code to a plain sentence in the user's language and folds the English
original into details. The English message text itself stays unchanged: the model reads
it, and other tests pin it.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from olga_companion import workspace
from olga_companion.agent import runtime, tool_validation, tools
from olga_companion.agent import pipe_table_tools
from olga_companion.llm.protocol import StreamResult, ToolCall
from olga_companion.pipe_table import PipeTable

_TABLES = Path(__file__).parent / "fixtures" / "pipe_tables"


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


def _tool_result(name: str, args: dict) -> dict:
    client = _Client([
        StreamResult(tool_calls=[ToolCall(name=name, args=args, call_id="c1")]),
        StreamResult(text="ok"),
    ])

    async def collect():
        return [e async for e in runtime.run_turn(client, "go")]

    events = asyncio.run(collect())
    return next(e.data["result"] for e in events if e.type == "tool_result")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    shutil.copyfile(_TABLES / "small_branch.csv", workspace_root / "small_branch.csv")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    return workspace_root


def test_a_missing_input_file_keeps_its_message_and_gains_a_code(root: Path) -> None:
    result = _tool_result("genkey_review", {"path": "missing.genkey"})

    assert result["error"].startswith("input file not found: 'missing.genkey'")
    assert result["error_code"] == "path_not_found"


def test_a_path_outside_the_workspace_has_its_own_code(root: Path) -> None:
    result = _tool_result("genkey_review", {"path": "../outside.genkey"})

    assert "workspace" in result["error"]
    assert result["error_code"] == "path_outside_workspace"


def test_the_workspace_error_itself_carries_the_code(root: Path) -> None:
    with pytest.raises(workspace.WorkspaceError) as missing:
        workspace.resolve_input_file("missing.genkey", {".genkey"})
    assert missing.value.error_code == "path_not_found"
    with pytest.raises(workspace.WorkspaceError) as outside:
        workspace.contained("../x")
    assert outside.value.error_code == "path_outside_workspace"


def test_an_unknown_table_node_is_coded() -> None:
    table = PipeTable(
        rows=({"from_node": "A", "to_node": "B"},), issues=(), header_row=1,
        ignored_columns=(), lines=(1,),
    )
    with pytest.raises(tools.ToolError) as raised:
        pipe_table_tools._with_chat_boundaries(table, [{"node": "Z", "kind": "sink"}])

    assert "which the table does not have" in str(raised.value)
    assert raised.value.error_code == "unknown_node"


def test_a_table_that_cannot_be_read_is_coded(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args, **_kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(pipe_table_tools, "read_table", broken)
    result = _tool_result("pipe_table_import", {
        "path": "small_branch.csv", "pvt_reference": "fluid.tab", "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"}, "end_time_s": 600,
    })

    assert result["error"].startswith("The table could not be read:")
    assert result["error_code"] == "table_unreadable"


def test_a_stale_workspace_is_coded(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def stale(_name, _args):
        raise workspace.StaleWorkspaceContextError("changed")

    monkeypatch.setattr(runtime.tools, "dispatch", stale)
    result = _tool_result("run_detect", {})

    assert result["error_code"] == "stale_workspace"


def test_an_uncoded_failure_adds_no_code_field(root: Path) -> None:
    result = _tool_result("genkey_review", {"path": "small_branch.csv"})

    assert "error" in result
    assert "error_code" not in result


def test_the_code_survives_the_dispatch_rewrap() -> None:
    cause = tool_validation.ToolError("x", error_code="unknown_node")
    wrapped = tool_validation.ToolError("x")
    wrapped.__cause__ = cause

    assert tool_validation.error_code_of(wrapped) == "unknown_node"
    assert tool_validation.error_code_of(ValueError("plain")) is None
