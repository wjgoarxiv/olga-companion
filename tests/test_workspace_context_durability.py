"""Workspace context durability failures remain fail-safe after invalidation."""

import errno
import json

import pytest

from olga_companion import config, workspace
from olga_companion.agent import approvals
from test_workspace import ws as ws


def test_context_parent_fsync_eio_is_fail_safe_after_invalidation(
    ws, tmp_path, monkeypatch
):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "case.genkey").write_text("x")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old))
    workspace.set_active_rel("case.genkey")
    minted = approvals.mint("run_execute", {"source": "old"})
    monkeypatch.setattr(
        config,
        "_fsync_parent_directory",
        lambda path: (_ for _ in ()).throw(
            OSError(errno.EIO, "injected parent fsync failure")
        ),
        raising=False,
    )

    with pytest.raises(OSError, match="parent fsync failure"):
        workspace.switch_root(new)

    identity = workspace.context_identity()
    assert identity in {(old.resolve(), 0), (new.resolve(), 1)}
    assert workspace.active() == {"name": None, "path": None}
    with pytest.raises(approvals.ApprovalError):
        approvals.consume(minted["token"], "run_execute", {"source": "old"})


def test_context_marker_parent_fsync_eio_leaves_first_switch_fail_closed(
    ws, tmp_path, monkeypatch
):
    context_path = tmp_path / "context-record.json"
    marker_path = tmp_path / "context-record.initialized"
    legacy_path = tmp_path / "legacy-root.json"
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "case.genkey").write_text("x")
    legacy_path.write_text(json.dumps({"root": str(old.resolve())}))
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: legacy_path)
    workspace.set_active_rel("case.genkey")
    minted = approvals.mint("run_execute", {"source": "legacy"})
    monkeypatch.setattr(
        config,
        "_fsync_parent_directory",
        lambda path: (_ for _ in ()).throw(
            OSError(errno.EIO, "injected marker parent fsync failure")
        ),
    )

    with pytest.raises(OSError, match="marker parent fsync failure"):
        workspace.switch_root(new)

    assert marker_path.exists() and not context_path.exists()
    assert workspace.active() == {"name": None, "path": None}
    with pytest.raises(config.WorkspaceContextError, match="missing|context"):
        workspace.context_identity()
    with pytest.raises(approvals.ApprovalError):
        approvals.consume(minted["token"], "run_execute", {"source": "legacy"})
