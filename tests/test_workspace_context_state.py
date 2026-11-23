"""Durable workspace context records, root switching, and API views."""

import json

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, workspace
from olga_companion.agent import approvals
from olga_companion.sidecar import app
from test_workspace import ws as ws


def test_context_generation_defaults_zero_and_tolerates_corruption(ws, monkeypatch):
    state = ws / "context-record.json"
    marker = ws / "context-record.initialized"
    monkeypatch.setattr(config, "_workspace_context_path", lambda: state, raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker, raising=False
    )
    assert workspace.context_generation() == 0
    state.write_text("not-json")
    with pytest.raises(config.WorkspaceContextError, match="malformed|context"):
        workspace.context_generation()
    state.write_text(json.dumps({"root": str(ws), "generation": -3}))
    with pytest.raises(config.WorkspaceContextError, match="generation|context"):
        workspace.context_generation()
    state.write_text(json.dumps({"root": str(ws), "generation": 0, "unexpected": True}))
    with pytest.raises(config.WorkspaceContextError, match="fields|context"):
        workspace.context_generation()


def test_missing_context_uses_stable_legacy_zero_then_migrates_atomically(
    ws, tmp_path, monkeypatch
):
    context_path = tmp_path / "context-record.json"
    marker_path = tmp_path / "context-record.initialized"
    legacy_path = tmp_path / "legacy-root.json"
    legacy_root = tmp_path / "legacy-root"
    legacy_root.mkdir()
    legacy_path.write_text(json.dumps({"root": str(legacy_root)}))
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: legacy_path)

    assert workspace.context_identity() == (legacy_root.resolve(), 0)
    config.set_workspace_root(str(legacy_root))

    assert context_path.is_file() and marker_path.is_file()
    assert json.loads(context_path.read_text()) == {
        "root": str(legacy_root.resolve()),
        "generation": 0,
    }
    assert workspace.context_identity() == (legacy_root.resolve(), 0)


def test_deleted_initialized_context_fails_closed_instead_of_resurrecting_legacy(
    ws, tmp_path, monkeypatch
):
    context_path = tmp_path / "context-record.json"
    marker_path = tmp_path / "context-record.initialized"
    legacy_path = tmp_path / "legacy-root.json"
    legacy_root = tmp_path / "legacy-root"
    selected_root = tmp_path / "selected-root"
    legacy_root.mkdir()
    selected_root.mkdir()
    legacy_path.write_text(json.dumps({"root": str(legacy_root)}))
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: legacy_path)
    config.set_workspace_root(str(selected_root))
    context_path.unlink()

    with pytest.raises(config.WorkspaceContextError, match="missing|context"):
        workspace.context_identity()


def test_deleting_context_and_marker_after_observation_fails_closed_in_process(
    ws, tmp_path, monkeypatch
):
    context_path = tmp_path / "context-record.json"
    marker_path = tmp_path / "context-record.initialized"
    root = tmp_path / "selected-root"
    root.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    config.set_workspace_root(str(root))
    assert workspace.context_identity() == (root.resolve(), 0)
    context_path.unlink()
    marker_path.unlink()

    with pytest.raises(
        config.WorkspaceContextError, match="missing|initialized|context"
    ):
        workspace.context_identity()


def test_switch_root_changes_generation_clears_active_and_revokes(
    ws, tmp_path, monkeypatch
):
    state = tmp_path / "context-record.json"
    marker = tmp_path / "context-record.initialized"
    override = tmp_path / "root.json"
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(config, "_workspace_context_path", lambda: state, raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: override)
    old = tmp_path / "old-root"
    new = tmp_path / "new-root"
    old.mkdir()
    new.mkdir()
    (old / "old.genkey").write_text("x")
    config.set_workspace_root(str(old))
    workspace.set_active_rel("old.genkey")
    token = approvals.mint("run_execute", {"source": "old"})

    context = workspace.switch_root(str(new))

    assert context["changed"] is True
    assert context["generation"] == 1
    assert context["revoked"] == 1
    assert context["active"] == {"name": None, "path": None}
    assert config.workspace_root().resolve() == new.resolve()
    with pytest.raises(approvals.ApprovalError):
        approvals.consume(token["token"], "run_execute", {"source": "old"})


def test_switch_same_resolved_root_preserves_active_generation_and_approvals(
    ws, tmp_path, monkeypatch
):
    state = tmp_path / "context-record.json"
    marker = tmp_path / "context-record.initialized"
    override = tmp_path / "root.json"
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(config, "_workspace_context_path", lambda: state, raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: override)
    root = tmp_path / "root"
    root.mkdir()
    case = root / "case.genkey"
    case.write_text("x")
    config.set_workspace_root(str(root))
    workspace.set_active_rel("case.genkey")
    token = approvals.mint("run_execute", {"source": "same"})

    context = workspace.switch_root(str(root / "."))

    assert context["changed"] is False
    assert context["generation"] == 0
    assert context["revoked"] == 0
    assert context["active"]["name"] == "case.genkey"
    approvals.consume(token["token"], "run_execute", {"source": "same"})


def test_legacy_workspace_root_endpoint_uses_safe_switch(ws, tmp_path, monkeypatch):
    state = tmp_path / "context-record.json"
    marker = tmp_path / "context-record.initialized"
    override = tmp_path / "root.json"
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(config, "_workspace_context_path", lambda: state, raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: override)
    token = __import__(
        "olga_companion.agent.session_token", fromlist=["boot_token"]
    ).boot_token()

    response = TestClient(app).post(
        "/api/workspace/root",
        json={"path": str(target)},
        headers={"X-Session-Token": token},
    )

    assert response.status_code == 200
    assert response.json()["generation"] == 1
    assert response.json()["changed"] is True


def test_workspace_list_and_context_expose_generation(ws, monkeypatch):
    monkeypatch.setattr(
        config,
        "_workspace_context_path",
        lambda: ws / "context-record.json",
        raising=False,
    )
    monkeypatch.setattr(
        config,
        "_workspace_context_marker_path",
        lambda: ws / "context-record.initialized",
        raising=False,
    )
    api = TestClient(app)
    assert api.get("/api/workspace/list").json()["generation"] == 0
    token = __import__(
        "olga_companion.agent.session_token", fromlist=["boot_token"]
    ).boot_token()
    context = api.get(
        "/api/workspace/context", headers={"X-Session-Token": token}
    ).json()
    assert context["generation"] == 0
    assert context["root"] == str(ws)


def test_environment_workspace_overrides_persisted_context_with_stable_generation(
    ws, tmp_path, monkeypatch
):
    persisted = tmp_path / "persisted"
    env_root = tmp_path / "env-root"
    other = tmp_path / "other"
    persisted.mkdir()
    env_root.mkdir()
    other.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.commit_workspace_context(persisted, 7)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(env_root))
    minted = approvals.mint("run_execute", {"source": "env"})

    assert workspace.context_identity() == (env_root.resolve(), 0)
    assert workspace.context_identity() == (env_root.resolve(), 0)
    same = workspace.switch_root(env_root / ".")
    assert same["changed"] is False and same["generation"] == 0 and same["revoked"] == 0
    approvals.consume(minted["token"], "run_execute", {"source": "env"})
    with pytest.raises(workspace.WorkspaceError, match="OLGA_WORKSPACE_DIR"):
        workspace.switch_root(other)
