"""Every directory fsync call site survives Windows EACCES."""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import pathlib
import traceback

import pytest

from olga_companion import config, save_as_recovery
from olga_companion import sidecar_save_as_retention as retention
from olga_companion.agent import pending_approvals
from olga_companion.llm import codex_oauth_cache


def _deny_directories(real_open, error: OSError):
    def open_path(path, flags, *args, **kwargs):
        if kwargs.get("dir_fd") is None and os.path.isdir(path):
            frames = traceback.extract_stack()
            cleanup = any(
                "shutil.py" in (frame.filename or "") or "tempfile.py" in (frame.filename or "")
                for frame in frames
            )
            if not cleanup:
                denied = error.__class__(error.errno, error.strerror, path)
                denied.errno = error.errno
                raise denied
        return real_open(path, flags, *args, **kwargs)

    return open_path


def _windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(pathlib, "WindowsPath", pathlib.PosixPath)
    monkeypatch.setattr(
        os,
        "open",
        _deny_directories(os.open, PermissionError(errno.EACCES, "Permission denied")),
    )


@pytest.fixture(autouse=True)
def _clear_approvals() -> None:
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def test_windows_eacces_still_registers_case_publish_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_APPROVAL_JOURNAL_DIR", str(tmp_path / "journal"))
    _windows(monkeypatch)

    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"transaction_id": "a" * 32},
        call_id="call-1",
        context_generation=0,
        session_id="session-1",
    )

    assert pending_approvals.is_actionable(
        pending_id,
        session_id="session-1",
        call_id="call-1",
        context_generation=0,
    )
    stored = pending_approvals.approval_journal.load_all()[pending_id]
    assert stored["approval"]["action_kind"] == "case_publish"


def test_posix_directory_eio_still_refuses_approval_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("OLGA_APPROVAL_JOURNAL_DIR", str(tmp_path / "journal"))
    assert os.name != "nt"
    monkeypatch.setattr(
        os,
        "open",
        _deny_directories(os.open, OSError(errno.EIO, "Input/output error")),
    )

    with pytest.raises(OSError):
        pending_approvals.register(
            action_kind="case_publish",
            args={"transaction_id": "b" * 32},
            call_id="call-2",
            context_generation=0,
            session_id="session-2",
        )


def test_windows_eacces_still_commits_workspace_context(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _windows(monkeypatch)

    root, generation = config.commit_workspace_context(workspace, 3)

    record = json.loads(config._workspace_context_path().read_text())
    assert root == workspace.resolve()
    assert generation == 3
    assert record["generation"] == 3


def test_windows_eacces_still_persists_save_as_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "private_state_root", lambda: tmp_path / "private")
    monkeypatch.setattr(save_as_recovery, "harden_private_path", lambda path, *, directory: None)
    backup = tmp_path / "backup.genkey"
    payload = b"reviewed-copy"
    backup.write_bytes(payload)
    _windows(monkeypatch)

    recovery_id = save_as_recovery.persist(
        tmp_path / "dest.genkey",
        backup,
        hashlib.sha256(payload).hexdigest(),
    )

    stored = tmp_path / "private" / "save-as-recovery" / f"{recovery_id}.json"
    assert json.loads(stored.read_text())["expected_hash"] == hashlib.sha256(payload).hexdigest()


def test_windows_eacces_still_writes_retention_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "harden_private_path", lambda path, *, directory: None)
    monkeypatch.setattr(retention, "_registry_path", lambda: tmp_path / "registry.json")
    _windows(monkeypatch)

    retention._write_registry([])

    assert json.loads((tmp_path / "registry.json").read_text())["directories"] == []


def test_windows_eacces_still_writes_codex_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_oauth_cache, "_harden_private_path", lambda path, *, directory: None)
    target = tmp_path / "codex" / "tokens.json"
    _windows(monkeypatch)

    codex_oauth_cache.atomic_write_app_tokens(target, {"access_token": "secret"})

    assert json.loads(target.read_text())["tokens"]["access_token"] == "secret"


def test_windows_eacces_still_deletes_codex_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_oauth_cache, "_harden_private_path", lambda path, *, directory: None)
    target = tmp_path / "codex" / "tokens.json"
    target.parent.mkdir()
    target.write_text("{}\n", encoding="utf-8")
    _windows(monkeypatch)

    removed = codex_oauth_cache.delete_app_tokens(
        target, logger=logging.getLogger("codex-test"), label="tokens"
    )

    assert removed is True
    assert not target.exists()


def test_windows_eacces_still_clears_codex_runtime_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_oauth_cache, "_harden_private_path", lambda path, *, directory: None)
    target = tmp_path / "codex" / "failure.json"
    _windows(monkeypatch)

    assert codex_oauth_cache.write_runtime_failure(target, 1.5) is True
    assert codex_oauth_cache.delete_runtime_failure(target) is True
    assert not target.exists()
