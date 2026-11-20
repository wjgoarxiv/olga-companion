"""Workspace context invalidation, atomicity, and concurrency scenarios."""

import errno
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, workspace
from olga_companion.agent import approvals, pending_approvals
from olga_companion.sidecar import app
from test_workspace import ws as ws

WorkerFailure = BaseException


def test_delayed_approval_execution_from_old_generation_fails_without_capability(
    ws, tmp_path, monkeypatch
):
    old = tmp_path / "approval-old"
    new = tmp_path / "approval-new"
    old.mkdir()
    new.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old))
    stale_generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": "old", "selection_id": "selection-old"},
        call_id="call-old",
        context_generation=stale_generation,
        session_id="abc123abc123",
    )
    workspace.switch_root(new)
    token = __import__(
        "olga_companion.agent.session_token", fromlist=["boot_token"]
    ).boot_token()

    response = TestClient(app).post(
        "/api/approvals/execute",
        json={
            "pending_id": pending_id,
            "session_id": "abc123abc123",
            "call_id": "call-old",
            "context_generation": stale_generation,
        },
        headers={"X-Session-Token": token},
    )

    assert response.status_code == 409
    assert approvals.revoke_all() == 0
    assert pending_approvals.revoke_all() == 1


def test_failed_switch_revokes_approvals_clears_active_and_keeps_old_context(
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
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: legacy_path)
    config.set_workspace_root(str(old))
    workspace.set_active_rel("case.genkey")
    minted = approvals.mint("run_execute", {"source": "old"})
    real_replace = config.os.replace

    def fail_context_commit(source, destination):
        if Path(destination) == context_path:
            raise OSError(errno.EIO, "injected context commit failure")
        return real_replace(source, destination)

    monkeypatch.setattr(config.os, "replace", fail_context_commit)

    with pytest.raises(OSError, match="commit failure"):
        workspace.switch_root(new)

    assert workspace.context_identity() == (old.resolve(), 0)
    assert workspace.active() == {"name": None, "path": None}
    with pytest.raises(approvals.ApprovalError):
        approvals.consume(minted["token"], "run_execute", {"source": "old"})


def test_context_reader_sees_only_atomic_old_or_new_pairs(ws, tmp_path, monkeypatch):
    context_path = tmp_path / "context-record.json"
    marker_path = tmp_path / "context-record.initialized"
    legacy_path = tmp_path / "legacy-root.json"
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: legacy_path)
    config.set_workspace_root(str(old))
    before_replace = threading.Event()
    allow_replace = threading.Event()
    real_replace = config.os.replace

    def block_context_replace(source, destination):
        if Path(destination) == context_path:
            before_replace.set()
            assert allow_replace.wait(2)
        return real_replace(source, destination)

    monkeypatch.setattr(config.os, "replace", block_context_replace)
    errors: list[BaseException] = []

    def writer():
        try:
            workspace.switch_root(new)
        except WorkerFailure as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    assert before_replace.wait(1)
    observed = {workspace.context_identity() for _ in range(25)}
    allow_replace.set()
    thread.join(2)
    observed.add(workspace.context_identity())

    assert not errors
    assert observed <= {(old.resolve(), 0), (new.resolve(), 1)}
    assert (old.resolve(), 0) in observed and (new.resolve(), 1) in observed


def test_context_snapshot_blocks_switch_and_never_mixes_identity_cases_or_active(
    ws, tmp_path, monkeypatch
):
    context_path = tmp_path / "context-record.json"
    marker_path = tmp_path / "context-record.initialized"
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "old.genkey").write_text("old")
    (new / "new.genkey").write_text("new")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    config.set_workspace_root(str(old))
    workspace.set_active_rel("old.genkey")
    old_snapshot = workspace.context_snapshot()
    before_replace = threading.Event()
    allow_replace = threading.Event()
    read_finished = threading.Event()
    snapshots: list[dict] = []
    real_replace = config.os.replace

    def block_context_replace(source, destination):
        if Path(destination) == context_path:
            before_replace.set()
            assert allow_replace.wait(2)
        return real_replace(source, destination)

    monkeypatch.setattr(config.os, "replace", block_context_replace)
    switch_thread = threading.Thread(target=lambda: workspace.switch_root(new))
    switch_thread.start()
    assert before_replace.wait(1)

    def reader():
        snapshots.append(workspace.context_snapshot())
        read_finished.set()

    read_thread = threading.Thread(target=reader)
    read_thread.start()
    assert not read_finished.wait(0.1), (
        "snapshot reader must wait for the root-switch writer lock"
    )
    allow_replace.set()
    switch_thread.join(2)
    read_thread.join(2)

    new_snapshot = snapshots[0]
    assert old_snapshot["root"] == str(old.resolve())
    assert old_snapshot["generation"] == 0
    assert [case["name"] for case in old_snapshot["cases"]] == ["old.genkey"]
    assert old_snapshot["active"]["name"] == "old.genkey"
    assert new_snapshot["root"] == str(new.resolve())
    assert new_snapshot["generation"] == 1
    assert [case["name"] for case in new_snapshot["cases"]] == ["new.genkey"]
    assert new_snapshot["active"] == {"name": None, "path": None}


def test_switch_holds_approval_revocation_barrier_through_context_commit(
    ws, tmp_path, monkeypatch
):
    context_path = tmp_path / "context-record.json"
    marker_path = tmp_path / "context-record.initialized"
    legacy_path = tmp_path / "legacy-root.json"
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(
        config, "_workspace_context_path", lambda: context_path, raising=False
    )
    monkeypatch.setattr(
        config, "_workspace_context_marker_path", lambda: marker_path, raising=False
    )
    monkeypatch.setattr(config, "_workspace_override_path", lambda: legacy_path)
    config.set_workspace_root(str(old))
    before_replace = threading.Event()
    allow_replace = threading.Event()
    mint_finished = threading.Event()
    real_replace = config.os.replace

    def block_context_replace(source, destination):
        if Path(destination) == context_path:
            before_replace.set()
            assert allow_replace.wait(2)
        return real_replace(source, destination)

    monkeypatch.setattr(config.os, "replace", block_context_replace)
    switch_thread = threading.Thread(target=lambda: workspace.switch_root(new))
    switch_thread.start()
    assert before_replace.wait(1)
    mint_thread = threading.Thread(
        target=lambda: (
            approvals.mint("run_execute", {"source": "concurrent"}),
            mint_finished.set(),
        )
    )
    mint_thread.start()

    assert not mint_finished.wait(0.1), (
        "mint must be blocked until changed context is committed"
    )
    allow_replace.set()
    switch_thread.join(2)
    mint_thread.join(2)

    assert mint_finished.is_set()
    assert workspace.context_identity() == (new.resolve(), 1)
