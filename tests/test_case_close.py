"""0.1.23 row 1: closing the open case returns the app to no case and touches no file."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from olga_companion import workspace
from olga_companion.agent.session_token import boot_token
from olga_companion.sidecar import app


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(workspace, "_active_state_path", lambda: tmp_path / "active.json")
    return root


def _close(generation: int, token: str | None = None):
    headers = {"X-Session-Token": token if token is not None else boot_token()}
    return TestClient(app).post(
        "/api/workspace/active/clear", json={"context_generation": generation}, headers=headers
    )


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_closing_the_open_case_leaves_no_case_and_every_file_as_it_was(ws) -> None:
    (ws / "a.genkey").write_text("A")
    (ws / "sub").mkdir()
    (ws / "sub" / "b.genkey").write_text("B")
    workspace.set_active_rel("a.genkey")
    before = _snapshot(ws)
    response = _close(workspace.context_generation())
    assert response.status_code == 200, response.text
    assert workspace.active() == {"name": None, "path": None}
    assert _snapshot(ws) == before


def test_closing_needs_the_session_token(ws) -> None:
    (ws / "a.genkey").write_text("A")
    workspace.set_active_rel("a.genkey")
    assert _close(workspace.context_generation(), token="wrong").status_code == 401
    assert workspace.active()["name"] == "a.genkey"


def test_a_close_from_an_older_workspace_context_is_refused(ws) -> None:
    (ws / "a.genkey").write_text("A")
    workspace.set_active_rel("a.genkey")
    assert _close(workspace.context_generation() + 1).status_code == 409
    assert workspace.active()["name"] == "a.genkey"


def test_closing_when_no_case_is_open_is_harmless(ws) -> None:
    assert _close(workspace.context_generation()).status_code == 200
    assert workspace.active() == {"name": None, "path": None}
