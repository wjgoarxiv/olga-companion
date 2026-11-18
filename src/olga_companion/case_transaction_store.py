"""Restart-safe private storage for reviewed CaseSpec transactions."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import config
from .case_transaction_models import TransactionPlan
from .private_path_acl import harden_private_path
from .sidecar_save_as_fsync import fsync_directory

_IDENTIFIER = re.compile(r"[0-9a-f]{32}")
_HASH = re.compile(r"[0-9a-f]{64}")


class TransactionStoreError(RuntimeError):
    """A private transaction record is absent, malformed, or unsafe."""


class _StoredRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1, le=1)
    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source: str | None
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiled_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    backup_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    publishable: bool
    validation_clean: bool
    context_generation: int = Field(ge=0)
    compiled_name: Literal["compiled.genkey"]
    backup_name: Literal["source.backup.genkey", "source.backup.json"]


@dataclass(frozen=True, slots=True)
class PublishTransaction:
    transaction_id: str
    source: Path | None
    source_hash: str
    compiled: Path
    compiled_hash: str
    backup: Path
    backup_hash: str
    publishable: bool
    validation_clean: bool
    context_generation: int


def _root() -> Path:
    configured = os.environ.get("OLGA_CASE_TRANSACTION_DIR")
    return (
        Path(configured).expanduser()
        if configured
        else config.private_state_root() / "case-transactions"
    )


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_root() -> Path:
    root = _root()
    if root.is_symlink():
        raise TransactionStoreError("Transaction root cannot be a symlink.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    harden_private_path(root, directory=True)
    return root.resolve()


def _write_fsynced(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        _ = handle.write(content)
        handle.flush()
        _ = os.fsync(handle.fileno())
    harden_private_path(path, directory=False)


def persist_transaction(
    plan: TransactionPlan,
    *,
    source: Path | None,
    backup_bytes: bytes,
    context_generation: int,
) -> PublishTransaction:
    """Commit a fully validated plan before its ID is exposed to approval."""
    root = _prepare_root()
    target = root / plan.transaction_id
    if target.exists() or target.is_symlink():
        raise TransactionStoreError("Transaction identity already exists.")
    temporary = Path(tempfile.mkdtemp(prefix=".transaction-", dir=root))
    try:
        harden_private_path(temporary, directory=True)
        compiled_name = "compiled.genkey"
        backup_name = "source.backup.genkey" if source is not None else "source.backup.json"
        compiled = temporary / compiled_name
        backup = temporary / backup_name
        backup_hash = _sha256_bytes(backup_bytes)
        _write_fsynced(compiled, plan.compiled_bytes)
        _write_fsynced(backup, backup_bytes)
        record = _StoredRecord(
            version=1,
            transaction_id=plan.transaction_id,
            source=str(source.resolve()) if source is not None else None,
            source_hash=plan.source_hash,
            compiled_hash=plan.compiled_hash,
            backup_hash=backup_hash,
            publishable=plan.publishable,
            validation_clean=plan.validation.clean,
            context_generation=context_generation,
            compiled_name=compiled_name,
            backup_name=backup_name,
        )
        _write_fsynced(
            temporary / "record.json",
            record.model_dump_json().encode("utf-8"),
        )
        fsync_directory(temporary)
        os.replace(temporary, target)
        fsync_directory(root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return load_transaction(plan.transaction_id)


def load_transaction(transaction_id: str) -> PublishTransaction:
    """Load and re-verify one immutable transaction for exact-once publish."""
    if _IDENTIFIER.fullmatch(transaction_id) is None:
        raise TransactionStoreError("Transaction identity is invalid.")
    root = _prepare_root()
    directory = root / transaction_id
    if directory.is_symlink() or not directory.is_dir():
        raise TransactionStoreError("Transaction does not exist safely.")
    record_path = directory / "record.json"
    if record_path.is_symlink() or not record_path.is_file():
        raise TransactionStoreError("Transaction record is malformed.")
    try:
        record = _StoredRecord.model_validate_json(
            record_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise TransactionStoreError("Transaction record is malformed.") from exc
    if record.transaction_id != transaction_id:
        raise TransactionStoreError("Transaction record identity disagrees.")
    expected_backup = "source.backup.genkey" if record.source is not None else "source.backup.json"
    if record.backup_name != expected_backup:
        raise TransactionStoreError("Transaction record is malformed.")
    if _HASH.fullmatch(record.source_hash) is None or _HASH.fullmatch(record.compiled_hash) is None:
        raise TransactionStoreError("Transaction hashes are malformed.")
    compiled = directory / record.compiled_name
    backup = directory / record.backup_name
    if any(path.is_symlink() or not path.is_file() for path in (compiled, backup)):
        raise TransactionStoreError("Transaction artifacts are unsafe or missing.")
    if _sha256_file(compiled) != record.compiled_hash or _sha256_file(backup) != record.backup_hash:
        raise TransactionStoreError("Transaction artifact hash disagrees.")
    source = Path(record.source) if record.source is not None else None
    return PublishTransaction(
        transaction_id=transaction_id,
        source=source,
        source_hash=record.source_hash,
        compiled=compiled,
        compiled_hash=record.compiled_hash,
        backup=backup,
        backup_hash=record.backup_hash,
        publishable=record.publishable,
        validation_clean=record.validation_clean,
        context_generation=record.context_generation,
    )
