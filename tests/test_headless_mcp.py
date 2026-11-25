"""The plugin's MCP server runs the app's own tools in this process, with no desktop app."""

from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from olga_companion import config, headless_mcp
from olga_companion.agent import tools

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    return workspace


def _rpc(*messages: dict) -> list[dict]:
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    headless_mcp.serve(stdin, stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def _call(name: str, arguments: dict) -> dict:
    (reply,) = _rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return reply["result"]


def test_initialize_says_the_harness_asks_before_writes():
    (reply,) = _rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    result = reply["result"]
    assert result["serverInfo"]["name"] == "olga-companion"
    assert "permission" in result["instructions"].lower()
    assert "new file" in result["instructions"].lower()


def test_lists_every_tool_without_approval_fields():
    (reply,) = _rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    listed = {tool["name"]: tool for tool in reply["result"]["tools"]}
    expected = {name for name in tools.TOOLS if name not in {"run_emergency_stop", "action_plan"}}
    if not config.native_tab_enabled():
        expected -= {"fluids_generate_tab"}
    assert set(listed) == expected
    for tool in listed.values():
        schema = json.dumps(tool["inputSchema"])
        assert "approval_token" not in schema and "idempotency_key" not in schema
    assert "approval_status" not in listed


def test_a_read_tool_runs_in_process():
    result = _call("olga_glossary", {"term": "ENDTIME"})
    assert result["isError"] is False
    assert "ENDTIME" in result["content"][0]["text"]


def test_a_case_in_the_workspace_is_reviewed(_workspace: Path):
    case = _workspace / "simple_pipeline.genkey"
    case.write_bytes((FIXTURES / "cases" / "simple_pipeline.genkey").read_bytes())
    result = _call("genkey_review", {"path": str(case)})
    assert result["isError"] is False, result
    assert "simple_pipeline" in result["content"][0]["text"]


def test_forged_approval_arguments_are_refused():
    result = _call("fluids_starter_tab", {"tab_rel": "a.tab", "approval_token": "x"})
    assert result["isError"] is True
    assert "approval_token" in result["content"][0]["text"]


def test_malformed_input_answers_an_error_and_keeps_serving():
    stdin = io.StringIO("not json\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
    stdout = io.StringIO()
    headless_mcp.serve(stdin, stdout)
    first, second = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert first["error"]["code"] == -32700
    assert second == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_no_socket_is_opened(monkeypatch: pytest.MonkeyPatch):
    def refuse(*_a, **_k):
        raise AssertionError("the headless server must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    _rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert _call("olga_glossary", {"term": "PIPE"})["isError"] is False


def test_defaults_use_the_cwd_and_a_private_data_folder(tmp_path: Path):
    env = headless_mcp.prepared_env({}, cwd=tmp_path)
    assert env["OLGA_WORKSPACE_DIR"] == str(tmp_path)
    assert Path(env["OLGA_APP_DATA_DIR"]) == config.private_state_root() / "headless"
    kept = headless_mcp.prepared_env({"OLGA_WORKSPACE_DIR": "/x", "OLGA_APP_DATA_DIR": "/y"}, cwd=tmp_path)
    assert kept["OLGA_WORKSPACE_DIR"] == "/x" and kept["OLGA_APP_DATA_DIR"] == "/y"


def test_the_module_entry_keeps_stdout_pure_json(tmp_path: Path):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "olga_glossary", "arguments": {"term": "ENDTIME"}}},
    ]
    run = subprocess.run(
        [sys.executable, "-m", "olga_companion.headless_mcp"],
        input="".join(json.dumps(m) + "\n" for m in lines),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        env={"PATH": "", "PYTHONPATH": str(ROOT / "src"), "OLGA_APP_DATA_DIR": str(tmp_path / "data"),
             "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "SYSTEMROOT": "C:\\Windows"},
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    replies = [json.loads(line) for line in run.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]


CHILD_NOISE = r'''
import subprocess, sys
from olga_companion import headless_mcp
reader, writer = headless_mcp._protocol_streams()
subprocess.run([sys.executable, "-c", "import sys; print('child noise'); print(repr(sys.stdin.read()))"])
print("parent noise")
writer.write(reader.readline())
writer.flush()
'''


def test_child_processes_cannot_touch_the_protocol_streams(tmp_path: Path):
    """A tool's child process that prints or reads stdin must neither corrupt nor eat the protocol."""
    run = subprocess.run(
        [sys.executable, "-c", CHILD_NOISE], input='{"jsonrpc":"2.0"}\n', capture_output=True, text=True,
        encoding="utf-8", cwd=tmp_path, env={**_child_env(tmp_path)}, timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == '{"jsonrpc":"2.0"}\n'
    assert "child noise" in run.stderr and "parent noise" in run.stderr
    assert "''" in run.stderr


def _child_env(tmp_path: Path) -> dict[str, str]:
    import os

    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "OLGA_APP_DATA_DIR": str(tmp_path / "data")}


def test_the_console_script_is_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'olga-companion-mcp = "olga_companion.headless_mcp:main"' in text


def test_an_exported_figure_says_where_it_was_saved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    figure = tmp_path / "appdata" / "fig.png"
    monkeypatch.setattr(tools, "dispatch", lambda *_a: {"artifact_id": "artifact_" + "0" * 32, "kind": "png"})
    monkeypatch.setattr("olga_companion.result_artifacts.resolve", lambda _id: figure)
    result = _call("results_plot", {"path": "workspace:case.ppl", "variables": ["PT"], "branch": "LINE"})
    body = json.loads(result["content"][0]["text"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert body["saved_path"] == str(figure)


def test_only_exports_carry_a_saved_path():
    assert "saved_path" not in _call("olga_glossary", {"term": "PIPE"})["content"][0]["text"]
