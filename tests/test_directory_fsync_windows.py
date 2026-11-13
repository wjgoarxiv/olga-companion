"""Directory fsync on Windows must not fail a reviewed plan or its publish."""

from __future__ import annotations

import errno
import hashlib
import os
import pathlib
import traceback

import pytest

from olga_companion.case_publish_types import PublishOutcomeUncertainError
from olga_companion.case_transaction_models import (
    BackupReceipt,
    RollbackReceipt,
    SemanticDiff,
    Snapshot,
    TransactionPlan,
    ValidationReceipt,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _plan() -> TransactionPlan:
    compiled = b"compiled-v1"
    digest = _sha(compiled)
    return TransactionPlan(
        transaction_id="c" * 32,
        transaction_hash=digest,
        source_hash=digest,
        working_hash=digest,
        compiled_hash=digest,
        compiled_bytes=compiled,
        snapshots=(Snapshot(index=0, spec_hash=digest, previous_hash=None),),
        semantic_diff=(SemanticDiff(path="ENDTIME", before=None, after=1),),
        text_diff=("ENDTIME",),
        backup=BackupReceipt(available=True, sha256=digest),
        validation=ValidationReceipt(
            clean=True, parser_clean=True, validator_clean=True, diagnostics=()
        ),
        rollback=RollbackReceipt(available=True, restore_hash=digest, source_unchanged=True),
    )


def _deny_directories(real_open, error: OSError):
    """Fail a product directory fsync, and leave shutil cleanup opens alone."""

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


def test_windows_directory_eacces_still_saves_and_publishes(tmp_path, monkeypatch):
    from olga_companion import case_publish, case_transaction_store
    from olga_companion.case_publish_types import PublishRequest, PublishTransactionSnapshot

    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(pathlib, "WindowsPath", pathlib.PosixPath)
    monkeypatch.setattr(
        case_transaction_store,
        "harden_private_path",
        lambda path, *, directory: None,
    )
    monkeypatch.setattr(
        os,
        "open",
        _deny_directories(os.open, PermissionError(errno.EACCES, "Permission denied")),
    )
    plan = _plan()
    stored = case_transaction_store.persist_transaction(
        plan, source=None, backup_bytes=plan.compiled_bytes, context_generation=1
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = PublishRequest(
        transaction_id=stored.transaction_id,
        source_hash=stored.source_hash,
        compiled_hash=stored.compiled_hash,
        destination_rel="reviewed.genkey",
        context_generation=1,
        idempotency_key="d" * 32,
    )
    snapshot = PublishTransactionSnapshot(
        transaction_id=stored.transaction_id,
        source=None,
        source_hash=stored.source_hash,
        compiled=stored.compiled,
        compiled_hash=stored.compiled_hash,
        backup=stored.backup,
        backup_hash=stored.backup_hash,
        validation_clean=stored.validation_clean,
        publishable=stored.publishable,
        context_generation=stored.context_generation,
    )

    receipt = case_publish.publish_case(
        request, snapshot, workspace, current_context_generation=1
    )

    assert receipt.state == "completed"
    assert (workspace / "reviewed.genkey").read_bytes() == plan.compiled_bytes


def test_posix_directory_fsync_error_still_raises(tmp_path, monkeypatch):
    from olga_companion import case_publish, case_transaction_store
    from olga_companion.case_publish_types import PublishRequest, PublishTransactionSnapshot

    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    assert os.name != "nt"
    monkeypatch.setattr(
        os,
        "open",
        _deny_directories(os.open, OSError(errno.EIO, "Input/output error")),
    )
    with pytest.raises(OSError):
        case_transaction_store.persist_transaction(
            _plan(), source=None, backup_bytes=b"backup", context_generation=1
        )

    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    compiled = private / "compiled.genkey"
    backup = private / "spec.json"
    compiled.write_bytes(b"compiled-v1")
    backup.write_bytes(b"spec")
    compiled_hash = _sha(compiled.read_bytes())
    backup_hash = _sha(backup.read_bytes())
    snapshot = PublishTransactionSnapshot(
        transaction_id="e" * 32,
        source=None,
        source_hash=backup_hash,
        compiled=compiled,
        compiled_hash=compiled_hash,
        backup=backup,
        backup_hash=backup_hash,
        validation_clean=True,
        publishable=True,
        context_generation=1,
    )
    request = PublishRequest(
        transaction_id=snapshot.transaction_id,
        source_hash=snapshot.source_hash,
        compiled_hash=snapshot.compiled_hash,
        destination_rel="reviewed.genkey",
        context_generation=1,
        idempotency_key="f" * 32,
    )
    with pytest.raises((OSError, PublishOutcomeUncertainError)):
        case_publish.publish_case(
            request, snapshot, workspace, current_context_generation=1
        )
