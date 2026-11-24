"""In the plugin, Claude Code's own permission prompt is the approval; the token never leaves."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from olga_companion import headless_mcp
from olga_companion.agent import approvals, tools

ROOT = Path(__file__).resolve().parents[1]
SIDE_EFFECT = {name for name, tool in tools.TOOLS.items() if tool.side_effect}
DIRECT = SIDE_EFFECT - {"action_plan"}


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    return workspace


def _serve(*messages: dict) -> tuple[list[dict], str]:
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    headless_mcp.serve(stdin, stdout)
    text = stdout.getvalue()
    return [json.loads(line) for line in text.splitlines()], text


def _call(name: str, arguments: dict) -> tuple[dict, str]:
    replies, text = _serve({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return replies[0]["result"], text


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Each side-effect call burns its token exactly as a real handler does, then records it."""
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(tools, "approval_payload", lambda name, args: {"probe": name})

    def dispatch(name: str, args: dict) -> dict:
        from olga_companion import workspace

        approvals.consume(args["approval_token"], name, {"probe": name}, context_generation=workspace.context_generation())
        seen.append((name, args))
        return {"ok": name}

    monkeypatch.setattr(tools, "dispatch", dispatch)
    return seen


@pytest.mark.parametrize("name", sorted(DIRECT))
def test_each_writer_reaches_its_handler_with_a_fresh_single_use_token(name: str, spy: list):
    result, text = _call(name, {})
    assert result["isError"] is False, result
    ((called, args),) = spy
    assert called == name
    assert args["approval_token"] not in text
    # The shape case_publish (and the app's pending store) uses for every writer's key.
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", args["idempotency_key"])
    with pytest.raises(approvals.ApprovalError):
        approvals.consume(args["approval_token"], name, {"probe": name})


def test_each_call_gets_its_own_idempotency_key(spy: list):
    _call("run_cancel", {})
    _call("run_cancel", {})
    assert spy[0][1]["idempotency_key"] != spy[1][1]["idempotency_key"]


def test_action_plan_is_not_offered_and_is_refused(spy: list):
    replies, _ = _serve({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "action_plan" not in {tool["name"] for tool in replies[0]["result"]["tools"]}
    result, _ = _call("action_plan", {"steps": []})
    assert result["isError"] is True
    assert spy == []


def test_writer_descriptions_say_the_harness_asks_first():
    replies, _ = _serve({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    listed = {tool["name"]: tool["description"] for tool in replies[0]["result"]["tools"]}
    for name in DIRECT:
        assert "Claude Code asks your permission before this runs." in listed[name], name
    for name in {"run_cancel", "sweep_cancel"}:
        assert "Stops" in listed[name]
    for name in DIRECT - {"run_cancel", "sweep_cancel"}:
        assert "new file" in listed[name]
    for name in set(listed) - SIDE_EFFECT:
        assert "permission" not in listed[name], name


def test_writers_force_a_prompt_and_readers_are_marked_read_only():
    replies, _ = _serve({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    for tool in replies[0]["result"]["tools"]:
        name = tool["name"]
        assert tool["title"], name
        asks = tool.get("_meta", {}).get("anthropic/requiresUserInteraction")
        if name in SIDE_EFFECT:
            assert tool["annotations"]["readOnlyHint"] is False, name
            assert asks is True, name
        else:
            assert tool["annotations"]["readOnlyHint"] is True, name
            assert asks is None, name


def test_the_plugin_ships_no_rule_that_allows_a_writer():
    plugin = ROOT / "plugin"
    texts = [p.read_text(encoding="utf-8") for p in plugin.rglob("*") if p.is_file()] if plugin.is_dir() else []
    for text in texts:
        assert "allowedTools" not in text and "permissions" not in text
        for name in SIDE_EFFECT:
            assert f"__{name}" not in text, name


def test_a_starter_table_is_written_through_tools_call(_workspace: Path):
    result, text = _call("fluids_starter_tab", {"tab_rel": "starter.tab"})
    assert result["isError"] is False, result
    assert (_workspace / "starter.tab").is_file()
    assert "approval_token" not in text


def test_only_known_modules_mint_tokens():
    minters = {
        path.relative_to(ROOT / "src").as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if re.search(r"approvals\.mint\(", path.read_text(encoding="utf-8"))
    }
    assert minters == {
        "olga_companion/agent/approval_execution.py",
        "olga_companion/agent/plan_execution.py",
        "olga_companion/case_delete.py",
        "olga_companion/run_companion_copy.py",
        "olga_companion/sidecar_case_edit_routes.py",
        "olga_companion/headless_mcp.py",
    }
