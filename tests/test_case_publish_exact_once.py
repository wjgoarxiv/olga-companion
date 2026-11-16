from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_publish_writes_once_and_replays_the_durable_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one reviewed transaction, exact approval binding, and empty destination.
    from olga_companion import case_publish
    from olga_companion.case_publish_types import PublishRequest, PublishTransactionSnapshot

    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    sandbox.mkdir()
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(sandbox / "journal"))
    source = workspace / "owner.genkey"
    compiled = sandbox / "compiled.genkey"
    backup = sandbox / "owner.genkey.bak"
    source.write_bytes(b"owner-v1")
    compiled.write_bytes(b"compiled-v1")
    backup.write_bytes(source.read_bytes())
    transaction = PublishTransactionSnapshot(
        transaction_id="a" * 32,
        source=source,
        source_hash=_sha256(source),
        compiled=compiled,
        compiled_hash=_sha256(compiled),
        backup=backup,
        backup_hash=_sha256(backup),
        validation_clean=True,
        publishable=True,
        context_generation=7,
    )
    request = PublishRequest(
        transaction_id=transaction.transaction_id,
        source_hash=transaction.source_hash,
        compiled_hash=transaction.compiled_hash,
        destination_rel="approved/new-case.genkey",
        context_generation=7,
        idempotency_key="p" * 32,
    )
    (workspace / "approved").mkdir()

    # When: the approved publish is dispatched twice with the server idempotency key.
    first = case_publish.publish_case(
        request, transaction, workspace, current_context_generation=7
    )
    replay = case_publish.publish_case(
        request, transaction, workspace, current_context_generation=7
    )

    # Then: one immutable file and one byte-identical authoritative receipt remain.
    destination = workspace / request.destination_rel
    assert destination.read_bytes() == b"compiled-v1"
    assert first == replay
    assert first.state == "completed"
    assert first.published_hash == transaction.compiled_hash
    assert first.destination_rel == request.destination_rel
    assert source.read_bytes() == b"owner-v1"


def test_publish_recovers_crash_after_file_commit_without_second_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid transaction whose first completed-receipt commit crashes.
    from olga_companion import case_publish
    from olga_companion import case_publish_journal
    from olga_companion.case_publish_types import (
        PublishOutcomeUncertainError,
        PublishRequest,
        PublishTransactionSnapshot,
    )

    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    sandbox.mkdir()
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(sandbox / "journal"))
    source = workspace / "owner.genkey"
    compiled = sandbox / "compiled.genkey"
    backup = sandbox / "owner.genkey.bak"
    source.write_bytes(b"owner-v1")
    compiled.write_bytes(b"compiled-v1")
    backup.write_bytes(source.read_bytes())
    transaction = PublishTransactionSnapshot(
        transaction_id="b" * 32,
        source=source,
        source_hash=_sha256(source),
        compiled=compiled,
        compiled_hash=_sha256(compiled),
        backup=backup,
        backup_hash=_sha256(backup),
        validation_clean=True,
        publishable=True,
        context_generation=3,
    )
    request = PublishRequest(
        transaction_id=transaction.transaction_id,
        source_hash=transaction.source_hash,
        compiled_hash=transaction.compiled_hash,
        destination_rel="approved/new-case.genkey",
        context_generation=3,
        idempotency_key="q" * 32,
    )
    (workspace / "approved").mkdir()
    original_commit = case_publish_journal.commit
    completed_attempts = 0

    def crash_once(record):
        nonlocal completed_attempts
        if record.state == "completed" and completed_attempts == 0:
            completed_attempts += 1
            raise OSError("simulated receipt crash")
        original_commit(record)

    monkeypatch.setattr(case_publish_journal, "commit", crash_once)

    # When: the process loses the receipt commit after the atomic link.
    with pytest.raises(PublishOutcomeUncertainError):
        case_publish.publish_case(
            request, transaction, workspace, current_context_generation=3
        )
    published_stat = (workspace / request.destination_rel).stat()
    recovered = case_publish.publish_case(
        request, transaction, workspace, current_context_generation=3
    )

    # Then: replay reconciles the exact hash and never replaces the file.
    assert recovered.state == "completed"
    assert (workspace / request.destination_rel).stat().st_ino == published_stat.st_ino
    assert completed_attempts == 1


def test_publish_reconciles_directory_fsync_failure_after_atomic_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an approved source-free transaction and failure after its atomic link.
    from olga_companion import case_publish
    from olga_companion.case_publish_types import (
        PublishOutcomeUncertainError,
        PublishRequest,
        PublishTransactionSnapshot,
    )

    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    compiled = private / "compiled.genkey"
    backup = private / "spec.json"
    compiled.write_bytes(b"compiled")
    backup.write_bytes(b"spec")
    transaction = PublishTransactionSnapshot(
        transaction_id="f" * 32,
        source=None,
        source_hash=_sha256(backup),
        compiled=compiled,
        compiled_hash=_sha256(compiled),
        backup=backup,
        backup_hash=_sha256(backup),
        validation_clean=True,
        publishable=True,
        context_generation=1,
    )
    request = PublishRequest(
        transaction_id=transaction.transaction_id,
        source_hash=transaction.source_hash,
        compiled_hash=transaction.compiled_hash,
        destination_rel="new.genkey",
        context_generation=1,
        idempotency_key="v" * 32,
    )
    real_install = case_publish._install_atomic

    def fail_after_link(destination: Path, content: bytes) -> None:
        real_install(destination, content)
        raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(case_publish, "_install_atomic", fail_after_link)

    # When: the link exists but the first dispatcher cannot confirm durability.
    with pytest.raises(PublishOutcomeUncertainError):
        case_publish.publish_case(
            request, transaction, workspace, current_context_generation=1
        )
    monkeypatch.setattr(case_publish, "_install_atomic", real_install)
    inode = (workspace / request.destination_rel).stat().st_ino
    receipt = case_publish.publish_case(
        request, transaction, workspace, current_context_generation=1
    )

    # Then: durable intent reconciles the exact file without replacing it.
    assert receipt.state == "completed"
    assert (workspace / request.destination_rel).stat().st_ino == inode
