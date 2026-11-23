"""A sandbox copy or any path outside the workspace cannot become the active case."""

import json
from pathlib import Path

import pytest

from olga_companion import config, workspace
from olga_companion.agent import tools

NOTICE = "샌드박스 복사본은 검토용이며 저장은 case_publish 승인으로"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(workspace, "_active_state_path", lambda: root / "active.json")
    return root


def _sandbox_copy(name: str = "case.modified.genkey") -> Path:
    copy = config.sandbox_root() / "runs" / "abc" / name
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text("reviewed copy")
    return copy


def test_sandbox_path_cannot_replace_the_active_case(ws):
    original = ws / "case.genkey"
    original.write_text("source")
    workspace.set_active_rel("case.genkey")
    copy = _sandbox_copy()

    with pytest.raises(workspace.WorkspaceError, match=NOTICE):
        workspace.set_active_path(str(copy))

    assert workspace.active_path() == str(original.resolve())
    assert workspace.active_workspace()["path"] == str(original.resolve())
    stored = workspace._active_state_path().read_text(encoding="utf-8")
    assert str(copy) not in stored
    assert NOTICE not in stored


def test_workspace_case_can_become_active(ws):
    original = ws / "case.genkey"
    other = ws / "other.genkey"
    original.write_text("source")
    other.write_text("other")
    workspace.set_active_rel("case.genkey")

    selected = workspace.set_active_path(str(other))

    assert selected["name"] == "other.genkey"
    assert workspace.active_path() == str(other.resolve())
    assert workspace.active_workspace()["name"] == "other.genkey"


def test_published_workspace_file_can_become_active(ws):
    original = ws / "case.genkey"
    published = ws / "reviewed-copy.genkey"
    original.write_text("source")
    workspace.set_active_rel("case.genkey")
    published.write_text("published sibling")

    selected = workspace.set_active_path(str(published))

    assert selected["path"] == str(published.resolve())
    assert workspace.active_path() == str(published.resolve())
    assert workspace.active_workspace()["name"] == "reviewed-copy.genkey"


def test_genkey_modify_keeps_the_workspace_case_and_tells_the_agent(ws, monkeypatch):
    original = ws / "case.genkey"
    original.write_text("source")
    workspace.set_active_rel("case.genkey")
    copy = _sandbox_copy()

    def fake_modify(*_args, **_kwargs):
        return {"source": str(original), "modified_copy": str(copy), "valid": True}

    monkeypatch.setattr(
        "olga_companion.genkey_static.modify_copy",
        fake_modify,
    )

    out = tools._t_genkey_modify(
        {"path": str(original), "keyword": "INTEGRATION", "key": "ENDTIME", "value": "7200 s"}
    )

    assert out["modified_copy"] == str(copy)
    assert NOTICE in str(out.get("notice"))
    assert workspace.active_path() == str(original.resolve())
    assert workspace.active_workspace()["path"] == str(original.resolve())


def test_stored_sandbox_path_is_forgotten_without_touching_the_copy(ws):
    original = ws / "case.genkey"
    original.write_bytes(b"source-bytes")
    copy = _sandbox_copy()
    copy.write_bytes(b"sandbox-bytes")
    workspace._active_state_path().write_text(
        json.dumps({"path": str(copy)}), encoding="utf-8"
    )

    assert workspace.active() == {"name": None, "path": None}
    assert workspace.active_workspace() == {"name": None, "path": None}
    assert workspace.active_path() is None
    assert not workspace._active_state_path().exists()
    assert copy.read_bytes() == b"sandbox-bytes"
    assert original.read_bytes() == b"source-bytes"


def test_stored_outside_path_is_forgotten_without_touching_the_file(ws, tmp_path):
    outside = tmp_path / "outside.genkey"
    outside.write_bytes(b"outside-bytes")
    workspace._active_state_path().write_text(
        json.dumps({"path": str(outside)}), encoding="utf-8"
    )

    assert workspace.active_path() is None
    assert workspace.active_workspace() == {"name": None, "path": None}
    assert not workspace._active_state_path().exists()
    assert outside.read_bytes() == b"outside-bytes"
