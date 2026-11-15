"""Fail-closed, atomic and exactly-once publication of reviewed GENKEY bytes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Final, NoReturn

from . import case_publish_journal
from .sidecar_save_as_fsync import fsync_directory
from .case_companion import CompanionVerificationError, verify_pvt_companion
from .case_compiler import LEGACY_PROVENANCE_MARKER, PROVENANCE_MARKER
from .case_publish_types import (
    PublishJournalRecord,
    PublishOutcomeUncertainError,
    PublishReceipt,
    PublishRefusedError,
    PublishRequest,
    PublishTransactionSnapshot,
)

_LOCK: Final = threading.Lock()
_PVT_FILE: Final = re.compile(rb'^FILES PVTFILE="([^"\r\n]+)"$', re.MULTILINE)
_BRANCH_FLUID: Final = re.compile(rb'^ BRANCH FLUID="([^"\r\n]+)"$', re.MULTILINE)
_DEVICE_NAME: Final = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
_RESERVED_CHARS: Final = set('<>:"/\\|?*')


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _refuse(code: str, detail: str) -> NoReturn:
    raise PublishRefusedError(code, detail)


def require_destination_companion(
    compiled: bytes,
    destination: Path,
    *,
    planned: Mapping[Path, str] | None = None,
) -> None:
    """OLGA resolves PVTFILE beside the case, so the table must sit by the destination.

    Only compiler-owned bytes carry a PVT reference and fluid label we can check; this
    primitive stays content-agnostic for everything else. ``planned`` maps the resolved path
    of a table that an earlier plan step will create to the label it will declare; only that
    exact table, under that exact label, may still be absent. Publishing never passes it.
    """
    if compiled.startswith(LEGACY_PROVENANCE_MARKER.encode("utf-8")):
        _refuse("legacy_compile", "This artifact came from CaseSpec v1 and was never solver-valid.")
    if not compiled.startswith(PROVENANCE_MARKER.encode("utf-8")):
        return
    pvt, fluid = _PVT_FILE.search(compiled), _BRANCH_FLUID.search(compiled)
    if pvt is None or fluid is None:
        _refuse("invalid_compile", "Compiled artifact has no PVT reference and fluid label.")
    reference, label = pvt[1].decode("utf-8"), fluid[1].decode("utf-8")
    expected = (destination.parent / reference).resolve()
    if planned and planned.get(expected) == label and not expected.exists():
        return
    try:
        _ = verify_pvt_companion(destination, reference, label)
    except CompanionVerificationError as exc:
        _refuse("pvt_companion", f"{exc} Place the table beside the destination case first.")


def _reserved_filename(name: str) -> bool:
    if not name or any(character in _RESERVED_CHARS or ord(character) < 32 for character in name):
        return True
    if name.endswith((" ", ".")):
        return True
    stem = name[: -len(".genkey")] if name.casefold().endswith(".genkey") else name
    return _DEVICE_NAME.fullmatch(stem) is not None or _DEVICE_NAME.fullmatch(stem.split(".", 1)[0]) is not None


def owner_reviewed_copy(compiled: bytes) -> bool:
    """True for a direct GENKEY copy, which is not a CaseSpec compiler artifact."""
    if compiled.startswith((
        PROVENANCE_MARKER.encode("utf-8"),
        LEGACY_PROVENANCE_MARKER.encode("utf-8"),
    )):
        return False
    return b"INTEGRATION" in compiled


def assert_publishable_destination(
    workspace_root: Path,
    destination_rel: str,
    transaction: PublishTransactionSnapshot,
) -> Path:
    """Resolve a destination and refuse escape, reserved names, and owner-copy folder changes."""
    compiled = transaction.compiled.read_bytes()
    if transaction.source is not None and owner_reviewed_copy(compiled):
        root = workspace_root.resolve(strict=True)
        relative = Path(destination_rel)
        try:
            parent_rel = transaction.source.resolve(strict=True).parent.relative_to(root)
        except (OSError, ValueError) as exc:
            raise PublishRefusedError("stale_source", "Source is not a contained file.") from exc
        if relative != parent_rel / relative.name:
            _refuse("unsafe_destination", "Reviewed copy must be saved beside the original.")
    return _destination(workspace_root, destination_rel)


def _destination(workspace_root: Path, destination_rel: str) -> Path:
    root = workspace_root.resolve(strict=True)
    relative = Path(destination_rel)
    if relative.is_absolute() or ".." in relative.parts:
        _refuse("unsafe_destination", "Destination must be workspace-relative.")
    if (
        relative.name.startswith("-")
        or relative.suffix.casefold() != ".genkey"
        or _reserved_filename(relative.name)
    ):
        _refuse("unsafe_destination", "Destination must be a safe .genkey filename.")
    candidate = root / relative
    cursor = root
    for part in relative.parts[:-1]:
        cursor /= part
        if cursor.is_symlink():
            _refuse("unsafe_destination", "Destination parents must not be symlinks.")
    try:
        parent = candidate.parent.resolve(strict=True)
        _ = parent.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise PublishRefusedError(
            "unsafe_destination", "Destination parent must exist inside the workspace."
        ) from exc
    if not parent.is_dir() or os.path.lexists(candidate):
        _refuse("destination_collision", "Destination already exists or is unavailable.")
    return candidate


def _validate_binding(
    request: PublishRequest,
    transaction: PublishTransactionSnapshot,
    current_context_generation: int,
) -> None:
    if request.transaction_id != transaction.transaction_id:
        _refuse("transaction_mismatch", "Transaction identity changed after review.")
    if request.source_hash != transaction.source_hash:
        _refuse("source_mismatch", "Approved source hash differs from the transaction.")
    if request.compiled_hash != transaction.compiled_hash:
        _refuse("compile_mismatch", "Approved compiled hash differs from the transaction.")
    if (
        request.context_generation != transaction.context_generation
        or request.context_generation != current_context_generation
    ):
        _refuse("stale_context", "Workspace context changed after review.")
    if not transaction.publishable or not transaction.validation_clean:
        _refuse("invalid_compile", "Transaction does not contain a clean publishable compile.")


def _validate_files(transaction: PublishTransactionSnapshot, workspace_root: Path) -> bytes:
    root = workspace_root.resolve(strict=True)
    if transaction.backup.is_symlink() or not transaction.backup.is_file():
        _refuse("missing_backup", "Transaction backup is missing or unsafe.")
    backup_hash = _sha256(transaction.backup)
    if backup_hash != transaction.backup_hash or backup_hash != transaction.source_hash:
        _refuse("invalid_backup", "Transaction backup does not match the reviewed source.")
    source_path = transaction.source
    if source_path is not None:
        try:
            source = source_path.resolve(strict=True)
            _ = source.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise PublishRefusedError(
                "stale_source", "Source is not a contained file."
            ) from exc
        if source_path.is_symlink() or not source.is_file():
            _refuse("stale_source", "Source must be a regular non-symlink file.")
        if _sha256(source) != transaction.source_hash:
            _refuse("stale_source", "Source changed after transaction review.")
    if transaction.compiled.is_symlink() or not transaction.compiled.is_file():
        _refuse("invalid_compile", "Compiled transaction artifact is missing or unsafe.")
    compiled = transaction.compiled.read_bytes()
    if hashlib.sha256(compiled).hexdigest() != transaction.compiled_hash:
        _refuse("invalid_compile", "Compiled artifact hash changed after review.")
    return compiled


def _receipt(request: PublishRequest, transaction: PublishTransactionSnapshot) -> PublishReceipt:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return PublishReceipt(
        receipt_id=hashlib.sha256(canonical).hexdigest(),
        transaction_id=request.transaction_id,
        source_hash=request.source_hash,
        compiled_hash=request.compiled_hash,
        published_hash=request.compiled_hash,
        backup_hash=transaction.backup_hash,
        destination_rel=request.destination_rel,
        context_generation=request.context_generation,
    )


def _install_atomic(destination: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".case-publish-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _ = os.link(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _matching_record(
    request: PublishRequest,
) -> PublishJournalRecord | None:
    record = case_publish_journal.load(request.transaction_id)
    if record is not None and record.request != request:
        _refuse(
            "reused_transaction",
            "Transaction was already bound to another approval or destination.",
        )
    return record


def publish_case(
    request: PublishRequest,
    transaction: PublishTransactionSnapshot,
    workspace_root: Path,
    *,
    current_context_generation: int,
) -> PublishReceipt:
    """Publish reviewed bytes once, reconciling a crash from durable intent."""
    with _LOCK:
        _validate_binding(request, transaction, current_context_generation)
        compiled = _validate_files(transaction, workspace_root)
        record = _matching_record(request)
        destination = workspace_root.resolve(strict=True) / request.destination_rel
        if record is not None and record.state == "completed":
            completed_receipt = record.receipt
            if completed_receipt is None or not destination.is_file():
                _refuse("receipt_mismatch", "Completed receipt has no matching destination.")
            if destination.is_symlink() or _sha256(destination) != request.compiled_hash:
                _refuse("receipt_mismatch", "Published destination changed after completion.")
            return completed_receipt
        if record is not None and os.path.lexists(destination):
            if destination.is_symlink() or not destination.is_file():
                _refuse("uncertain_publish", "Publish intent conflicts with destination state.")
            if _sha256(destination) != request.compiled_hash:
                _refuse("uncertain_publish", "Publish intent destination has another hash.")
        else:
            destination = assert_publishable_destination(
                workspace_root, request.destination_rel, transaction
            )
            require_destination_companion(compiled, destination)
            case_publish_journal.commit(
                PublishJournalRecord(state="intent", request=request)
            )
            try:
                _install_atomic(destination, compiled)
            except FileExistsError as exc:
                raise PublishRefusedError(
                    "destination_collision", "Destination appeared during publish."
                ) from exc
            except OSError as exc:
                if (
                    destination.is_file()
                    and not destination.is_symlink()
                    and _sha256(destination) == request.compiled_hash
                ):
                    raise PublishOutcomeUncertainError(request.transaction_id) from exc
                raise PublishRefusedError(
                    "publish_io", "Destination could not be committed atomically."
                ) from exc
            source = transaction.source
            if source is not None and _sha256(source) != transaction.source_hash:
                try:
                    destination.unlink()
                except OSError as exc:
                    raise PublishOutcomeUncertainError(
                        request.transaction_id
                    ) from exc
                _refuse("stale_source", "Source changed during atomic publication.")
        receipt = _receipt(request, transaction)
        try:
            case_publish_journal.commit(
                PublishJournalRecord(state="completed", request=request, receipt=receipt)
            )
        except OSError as exc:
            raise PublishOutcomeUncertainError(request.transaction_id) from exc
        return receipt
