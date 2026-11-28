"""Through the plugin, a write always makes a new file: an existing case, table or result is never overwritten."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from olga_companion import headless_mcp
from olga_companion.agent import approvals, tools

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_OLGA = FIXTURES / "fake_olga" / "fake_olga.py"
CSV = "P (bar),T (C),ROG,ROHL,VISG,VISHL\n" + "".join(
    f"{p},{t},{1.0 + p},{800 + p},1.1e-05,0.002\n" for p in (1, 5, 10) for t in (10, 30)
)
ORIGINAL = b"ORIGINAL BYTES - must survive\n"


@pytest.fixture(autouse=True)
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    return root


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _call(name: str, arguments: dict) -> dict:
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}) + "\n")
    stdout = io.StringIO()
    headless_mcp.serve(stdin, stdout)
    return json.loads(stdout.getvalue())["result"]


def _existing(ws: Path, rel: str) -> Path:
    path = ws / rel
    path.write_bytes(ORIGINAL)
    return path


# ---- the tools themselves refuse (no backstop: `_approved` is the post-permission step)


def test_starter_tab_refuses_an_existing_table(ws: Path):
    target = _existing(ws, "old.tab")
    with pytest.raises((tools.ToolError, ValueError), match="exist"):
        headless_mcp._approved("fluids_starter_tab", {"tab_rel": "old.tab"})
    assert target.read_bytes() == ORIGINAL


def test_import_tab_refuses_an_existing_table(ws: Path):
    (ws / "props.csv").write_text(CSV, encoding="utf-8")
    target = _existing(ws, "old.tab")
    with pytest.raises((tools.ToolError, ValueError), match="exist"):
        headless_mcp._approved("fluids_import_tab", {"source_rel": "props.csv", "tab_rel": "old.tab", "fluid_label": "A"})
    assert target.read_bytes() == ORIGINAL


def _fluid(ws: Path) -> None:
    shutil.copy2(FIXTURES / "fluids" / "fluid.tab", ws / "fluid.tab")


def test_genkey_save_refuses_an_existing_case(ws: Path):
    _fluid(ws)
    target = _existing(ws, "old.genkey")
    with pytest.raises((tools.ToolError, ValueError), match="exist"):
        headless_mcp._approved("genkey_save", {"save_rel": "old.genkey", "topology": "simple_pipeline", "pvtfile": "./fluid.tab"})
    assert target.read_bytes() == ORIGINAL


def test_new_destinations_are_written(ws: Path):
    (ws / "props.csv").write_text(CSV, encoding="utf-8")
    assert _call("fluids_starter_tab", {"tab_rel": "a.tab"})["isError"] is False
    assert _call("fluids_import_tab", {"source_rel": "props.csv", "tab_rel": "b.tab", "fluid_label": "B"})["isError"] is False
    _fluid(ws)
    assert _call("genkey_save", {"save_rel": "c.genkey", "topology": "simple_pipeline", "pvtfile": "./fluid.tab"})["isError"] is False
    assert {p.name for p in ws.iterdir()} >= {"a.tab", "b.tab", "c.genkey"}


def test_case_publish_writes_a_new_case_through_real_dispatch(ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from case_spec_v2_support import PVT_TABLE_TEXT
    from test_case_publish_tool_integration import _spec

    from olga_companion import workspace
    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    (ws / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    spec = _spec()
    plan = plan_case_edits(
        spec, [{"op": "set_integration", "end_time_s": 7200.0}], expected_hash=case_spec_hash(spec),
        workspace_root=ws, context_generation=workspace.context_generation(),
    )
    assert plan.publishable is True, getattr(plan, "errors", plan)
    result = _call("case_publish", {
        "transaction_id": plan.transaction_id, "source_hash": plan.source_hash, "compiled_hash": plan.compiled_hash,
        "destination_rel": "published.genkey", "context_generation": workspace.context_generation(),
    })
    assert result["isError"] is False, result["content"][0]["text"]
    assert _sha(ws / "published.genkey") == plan.compiled_hash


def test_an_unexpected_tool_failure_is_an_error_answer_not_a_dead_server(monkeypatch: pytest.MonkeyPatch):
    def boom(*_a, **_k):
        raise PermissionError("denied by the OS")

    monkeypatch.setattr(tools, "dispatch", boom)
    stdin = io.StringIO("".join(
        json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "fluids_starter_tab", "arguments": {"tab_rel": f"n{i}.tab"}}}) + "\n"
        for i in (1, 2)
    ))
    stdout = io.StringIO()
    headless_mcp.serve(stdin, stdout)
    answers = [json.loads(line) for line in stdout.getvalue().splitlines()]
    # Tool calls run on worker threads (review 2026-11-27, row 1), so replies match by id, not arrival order.
    assert sorted(a["id"] for a in answers) == [1, 2]
    assert all(a["result"]["isError"] is True for a in answers)
    assert "denied by the OS" not in stdout.getvalue()


def test_draft_mfl_refuses_when_its_default_table_already_exists(ws: Path, monkeypatch: pytest.MonkeyPatch):
    target = _existing(ws, "x.tab")
    before = _sha(target)
    minted: list[str] = []
    monkeypatch.setattr(approvals, "mint", lambda *a, **k: minted.append(a[0]) or {"token": "t"})
    result = _call("fluids_draft_mfl", {"mfl_rel": "x.mfl"})
    assert result["isError"] is True
    assert "already exists" in result["content"][0]["text"]
    assert minted == []
    assert _sha(target) == before


# ---- the headless backstop refuses before any token exists


@pytest.mark.parametrize(
    ("name", "key", "rel"),
    [
        ("fluids_starter_tab", "tab_rel", "x.tab"),
        ("fluids_import_tab", "tab_rel", "x.tab"),
        ("fluids_draft_mfl", "mfl_rel", "x.mfl"),
        ("fluids_draft_mfl", "tab_rel", "x.tab"),
        ("genkey_save", "save_rel", "x.genkey"),
        ("case_publish", "destination_rel", "x.genkey"),
    ],
)
def test_an_existing_destination_is_refused_before_minting(ws: Path, monkeypatch: pytest.MonkeyPatch, name: str, key: str, rel: str):
    target = _existing(ws, rel)
    before = _sha(target)
    minted: list[str] = []
    monkeypatch.setattr(approvals, "mint", lambda *a, **k: minted.append(a[0]) or {"token": "t"})
    result = _call(name, {key: rel})
    assert result["isError"] is True
    assert "already exists" in result["content"][0]["text"]
    assert minted == []
    assert _sha(target) == before


def test_a_destination_outside_the_workspace_is_refused(ws: Path, monkeypatch: pytest.MonkeyPatch):
    minted: list[str] = []
    monkeypatch.setattr(approvals, "mint", lambda *a, **k: minted.append(a[0]) or {"token": "t"})
    result = _call("fluids_starter_tab", {"tab_rel": "../escape.tab"})
    assert result["isError"] is True
    assert minted == []
    assert not (ws.parent / "escape.tab").exists()


# ---- a run writes into a new run folder and leaves the case files alone


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="the fake runtime's direct copy needs os.fchmod (Windows: Python 3.13+)")
def test_a_run_leaves_the_case_and_its_table_unchanged(ws: Path, monkeypatch: pytest.MonkeyPatch):
    from olga_companion import runner
    from olga_companion.config import sandbox_root

    case = ws / "case.genkey"
    case.write_text((FIXTURES / "cases" / "simple_pipeline.genkey").read_text().replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FIXTURES / "fluids" / "fluid.tab", ws / "fluid.tab")
    inputs = {p: _sha(p) for p in ws.iterdir()}
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    runs = sandbox_root() / "runs"
    before = set(runs.iterdir()) if runs.exists() else set()

    preview = json.loads(_call("run_preview", {"source": str(case)})["content"][0]["text"].split("\n", 1)[1].rsplit("\n", 1)[0])
    started = _call("run_execute", {"source": str(case), "selection_id": preview["selection_id"], "timeout_s": 3600})
    assert started["isError"] is False, started
    body = json.loads(started["content"][0]["text"].split("\n", 1)[1].rsplit("\n", 1)[0])
    deadline = time.monotonic() + 20
    while runner.run_status(body["run_id"])["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.2)

    after = set(runs.iterdir())
    assert len(after - before) == 1
    assert Path(body["run_dir"]) in after - before
    assert {p: _sha(p) for p in inputs} == inputs
    assert {p.name for p in ws.iterdir()} == {p.name for p in inputs}
