"""Workspace case listing, containment, and active-case behavior."""

import json
import threading

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from olga_companion import workspace
from olga_companion.sidecar import app


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    # Isolate the active-state file to the temp dir (default lives under project var/).
    monkeypatch.setattr(
        workspace, "_active_state_path", lambda: tmp_path / "active.json"
    )
    return tmp_path


def test_list_cases_only_genkey_and_tab(ws):
    (ws / "a.genkey").write_text("x")
    (ws / "b.tab").write_text("y")
    (ws / "notes.txt").write_text("z")
    (ws / "sub").mkdir()
    (ws / "sub" / "c.genkey").write_text("w")
    cases = workspace.list_cases()
    assert {c["name"] for c in cases} == {"a.genkey", "b.tab", "c.genkey"}
    # the nested case is identified by a workspace-relative rel, never an absolute path
    rels = {c["rel"] for c in cases}
    assert any(r.replace("\\", "/") == "sub/c.genkey" for r in rels)
    assert all("rel" in c and "name" in c and "size" in c for c in cases)


def test_contained_refuses_traversal_and_absolute(ws):
    with pytest.raises(workspace.WorkspaceError):
        workspace.contained("../escape.genkey")
    with pytest.raises(workspace.WorkspaceError):
        workspace.contained("../../etc/passwd")
    with pytest.raises(workspace.WorkspaceError):
        workspace.contained("/etc/passwd")


def test_set_active_rel_roundtrip(ws):
    (ws / "case.genkey").write_text("x")
    result = workspace.set_active_rel("case.genkey")
    assert result["name"] == "case.genkey"
    assert workspace.active()["name"] == "case.genkey"
    assert workspace.active_path().endswith("case.genkey")


def test_workspace_active_api_is_generation_bound_and_latest_selection_wins(
    ws, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given delayed A then B, When B completes first, Then A cannot overwrite B."""
    (ws / "A.genkey").write_text("A")
    (ws / "B.genkey").write_text("B")
    entered_a = threading.Event()
    release_a = threading.Event()
    real_set_active = workspace.set_active_rel

    def delayed_set_active(rel: str, *args, **kwargs):
        if rel == "A.genkey":
            entered_a.set()
            assert release_a.wait(2)
        return real_set_active(rel, *args, **kwargs)

    monkeypatch.setattr(workspace, "set_active_rel", delayed_set_active)
    token = __import__(
        "olga_companion.agent.session_token", fromlist=["boot_token"]
    ).boot_token()
    headers = {"X-Session-Token": token}
    generation = workspace.context_generation()
    responses: dict[str, Response] = {}

    def select_a() -> None:
        responses["A"] = TestClient(app).post(
            "/api/workspace/active",
            json={"rel": "A.genkey", "context_generation": generation},
            headers=headers,
        )

    thread = threading.Thread(target=select_a)
    thread.start()
    assert entered_a.wait(1)
    response_b = TestClient(app).post(
        "/api/workspace/active",
        json={"rel": "B.genkey", "context_generation": generation},
        headers=headers,
    )
    release_a.set()
    thread.join(2)

    response_a = responses["A"]
    assert response_b.status_code == 200
    assert response_a.status_code == 409
    assert workspace.active()["name"] == "B.genkey"


def test_set_active_rel_refuses_escape(ws):
    with pytest.raises(workspace.WorkspaceError):
        workspace.set_active_rel("../outside.genkey")


def test_set_active_rel_refuses_non_case(ws):
    (ws / "notes.txt").write_text("z")
    with pytest.raises(workspace.WorkspaceError):
        workspace.set_active_rel("notes.txt")


def test_active_is_empty_when_unset_or_stale(ws):
    assert workspace.active() == {"name": None, "path": None}
    (ws / "case.genkey").write_text("x")
    workspace.set_active_rel("case.genkey")
    (ws / "case.genkey").unlink()  # active file disappears
    assert workspace.active() == {"name": None, "path": None}


def test_contained_refuses_symlink_escape(ws, tmp_path):
    # A symlink inside the workspace that points OUTSIDE it must not slip through:
    # contained() resolve()s the link, so the escape is caught.
    outside = tmp_path.parent / "secret_case.genkey"
    outside.write_text("secret")
    link = ws / "link.genkey"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        import pytest as _pytest

        _pytest.skip("symlinks unavailable on this platform")
    try:
        with pytest.raises(workspace.WorkspaceError):
            workspace.contained("link.genkey")
        # …and it is dropped from the listing rather than exposing the outside file.
        assert all(c["name"] != "link.genkey" for c in workspace.list_cases())
    finally:
        outside.unlink()


def test_set_active_path_agent_rejects_outside_file(ws, tmp_path):
    outside = tmp_path.parent / "agent_outside.genkey"
    outside.write_text("x")
    try:
        with pytest.raises(workspace.WorkspaceError, match="workspace or app sandbox"):
            workspace.set_active_path(str(outside))
        assert workspace.active_path() is None
    finally:
        outside.unlink()


def test_active_workspace_rejects_stale_external_agent_case(ws, tmp_path):
    outside = tmp_path.parent / "external_active.genkey"
    outside.write_text("x")
    try:
        workspace._active_state_path().write_text(json.dumps({"path": str(outside)}))

        assert workspace.active_workspace() == {"name": None, "path": None}
        assert workspace.active_path() is None

        inside = ws / "inside.genkey"
        inside.write_text("x")
        workspace.set_active_rel("inside.genkey")
        assert workspace.active_workspace() == {
            "name": "inside.genkey",
            "path": str(inside.resolve()),
        }
    finally:
        outside.unlink()


def test_workspace_active_api_uses_contained_view(ws, tmp_path):
    outside = tmp_path.parent / "api_external_active.genkey"
    outside.write_text("x")
    try:
        workspace._active_state_path().write_text(json.dumps({"path": str(outside)}))
        assert TestClient(app).get("/api/workspace/active").json() == {
            "name": None,
            "path": None,
        }
    finally:
        outside.unlink()
