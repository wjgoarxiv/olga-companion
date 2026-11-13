from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from olga_companion import case_publish
from olga_companion.case_publish_types import (
    PublishRefusedError,
    PublishRequest,
    PublishTransactionSnapshot,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reviewed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, PublishRequest, PublishTransactionSnapshot]:
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
        transaction_id="c" * 32,
        source=source,
        source_hash=_sha256(source),
        compiled=compiled,
        compiled_hash=_sha256(compiled),
        backup=backup,
        backup_hash=_sha256(backup),
        validation_clean=True,
        publishable=True,
        context_generation=4,
    )
    request = PublishRequest(
        transaction_id=transaction.transaction_id,
        source_hash=transaction.source_hash,
        compiled_hash=transaction.compiled_hash,
        destination_rel="approved.genkey",
        context_generation=4,
        idempotency_key="r" * 32,
    )
    return workspace, request, transaction


def _publish(
    workspace: Path,
    request: PublishRequest,
    transaction: PublishTransactionSnapshot,
    generation: int = 4,
):
    return case_publish.publish_case(
        request,
        transaction,
        workspace,
        current_context_generation=generation,
    )


def test_publish_refuses_stale_source_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: source bytes changed after review.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)
    source = transaction.source
    assert source is not None
    source.write_bytes(b"owner-v2")

    # When / Then: the stale transaction is inert.
    with pytest.raises(PublishRefusedError, match="stale_source"):
        _publish(workspace, request, transaction)
    assert not (workspace / request.destination_rel).exists()


def test_publish_accepts_source_free_casespec_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a G005 CaseSpec transaction backed by canonical JSON, not an owner case.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)
    canonical_spec = transaction.backup
    canonical_spec.write_bytes(b'{"version":"1"}')
    spec_hash = _sha256(canonical_spec)
    transaction = replace(
        transaction,
        source=None,
        source_hash=spec_hash,
        backup_hash=spec_hash,
    )
    request = request.model_copy(update={"source_hash": spec_hash})

    # When: the exact validated compile is approved for a new workspace file.
    receipt = _publish(workspace, request, transaction)

    # Then: publication succeeds without inventing or mutating an owner source.
    assert receipt.source_hash == spec_hash
    assert (workspace / request.destination_rel).read_bytes() == b"compiled-v1"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("invalid", "invalid_compile"),
        ("missing_backup", "missing_backup"),
        ("bad_backup", "invalid_backup"),
        ("stale_compiled", "invalid_compile"),
    ],
)
def test_publish_refuses_untrusted_transaction_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    code: str,
) -> None:
    # Given: one reviewed transaction whose required proof is no longer valid.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)
    if change == "invalid":
        transaction = replace(transaction, validation_clean=False)
    elif change == "missing_backup":
        transaction.backup.unlink()
    elif change == "bad_backup":
        transaction.backup.write_bytes(b"wrong")
    elif change == "stale_compiled":
        transaction.compiled.write_bytes(b"changed")

    # When / Then: publication is refused before destination creation.
    with pytest.raises(PublishRefusedError, match=code):
        _publish(workspace, request, transaction)
    assert not (workspace / request.destination_rel).exists()


def test_publish_refuses_context_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the workspace generation advanced after approval.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)

    # When / Then: the old approval cannot cross the context barrier.
    with pytest.raises(PublishRefusedError, match="stale_context"):
        _publish(workspace, request, transaction, generation=5)
    assert not (workspace / request.destination_rel).exists()


@pytest.mark.parametrize("destination", ["../escape.genkey", "/tmp/escape.genkey"])
def test_publish_refuses_destination_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    destination: str,
) -> None:
    # Given: an approval payload with a non-contained destination.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)
    request = request.model_copy(update={"destination_rel": destination})

    # When / Then: no file escapes the workspace.
    with pytest.raises(PublishRefusedError, match="unsafe_destination"):
        _publish(workspace, request, transaction)
    assert not (tmp_path / "escape.genkey").exists()


def test_publish_refuses_symlink_parent_and_existing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one symlinked parent and one existing destination.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    linked = request.model_copy(update={"destination_rel": "linked/new.genkey"})

    # When / Then: symlink traversal and overwrite are both refused.
    with pytest.raises(PublishRefusedError, match="unsafe_destination"):
        _publish(workspace, linked, transaction)
    (workspace / request.destination_rel).write_bytes(b"existing")
    with pytest.raises(PublishRefusedError, match="destination_collision"):
        _publish(workspace, request, transaction)
    assert not (outside / "new.genkey").exists()


def test_publish_refuses_rebinding_a_used_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one transaction already completed for one exact approval binding.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)
    _publish(workspace, request, transaction)
    rebound = request.model_copy(
        update={"destination_rel": "second.genkey", "idempotency_key": "s" * 32}
    )

    # When / Then: a new approval cannot repurpose that transaction.
    with pytest.raises(PublishRefusedError, match="reused_transaction"):
        _publish(workspace, rebound, transaction)
    assert not (workspace / "second.genkey").exists()


def test_source_mutation_race_rolls_back_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: source mutation occurs immediately after atomic destination install.
    workspace, request, transaction = _reviewed(tmp_path, monkeypatch)
    original_install = case_publish._install_atomic
    source = transaction.source
    assert source is not None

    def mutate_after_install(destination: Path, content: bytes) -> None:
        original_install(destination, content)
        source.write_bytes(b"raced")

    monkeypatch.setattr(case_publish, "_install_atomic", mutate_after_install)

    # When / Then: no published destination survives the source race.
    with pytest.raises(PublishRefusedError, match="stale_source"):
        _publish(workspace, request, transaction)
    assert not (workspace / request.destination_rel).exists()
