from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import secrets
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any


def _facade() -> Any:
    from . import sidecar

    return sidecar


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SaveAsRecoveryRequiredError(OSError):
    """The destination could not be restored; a verified recovery backup remains."""

    code = "save_as_recovery_required"
    public_message = "Save As could not safely restore the previous destination. Manual recovery is required."

    def __init__(self, destination: Path, backup_path: Path, expected_hash: str):
        self.destination = destination
        self.backup_path = backup_path
        self.expected_hash = expected_hash
        super().__init__(self.public_message)


def private_sibling_path(destination: Path, label: str, suffix: str) -> Path:
    for _ in range(32):
        candidate = destination.parent / (
            f".{destination.name}.{label}.{secrets.token_hex(8)}{suffix}"
        )
        if not candidate.exists():
            return candidate
    raise OSError(errno.EEXIST, "Could not allocate a private sibling recovery path.")


def copy_verified(source: Path, destination: Path, expected_hash: str) -> None:
    sidecar = _facade()
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if sidecar._sha256(destination) != expected_hash:
            raise OSError(errno.EIO, "Verified copy hash mismatch.")
    except BaseException:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        with suppress(OSError):
            destination.unlink(missing_ok=True)
        raise


def create_verified_backup(destination: Path, expected_hash: str) -> Path:
    """Create a durable sibling backup without moving or deleting destination."""
    sidecar = _facade()
    backup = sidecar._private_sibling_path(destination, "recovery", ".bak")
    try:
        sidecar._copy_verified(destination, backup, expected_hash)
        if (
            sidecar._sha256(destination) != expected_hash
            or sidecar._sha256(backup) != expected_hash
        ):
            raise OSError(
                errno.EIO,
                "Destination changed while creating its recovery backup.",
            )
        sidecar._fsync_directory(destination.parent)
        if (
            sidecar._sha256(destination) != expected_hash
            or sidecar._sha256(backup) != expected_hash
        ):
            raise OSError(
                errno.EIO,
                "Destination changed while durably recording its recovery backup.",
            )
        return backup
    except BaseException:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        with suppress(OSError):
            backup.unlink(missing_ok=True)
        raise


def restore_attempt(
    backup: Path,
    destination: Path,
    expected_hash: str,
    label: str,
) -> None:
    sidecar = _facade()
    restore_temp = sidecar._private_sibling_path(destination, label, ".tmp")
    try:
        sidecar._copy_verified(backup, restore_temp, expected_hash)
        os.replace(restore_temp, destination)
        if sidecar._sha256(destination) != expected_hash:
            raise OSError(errno.EIO, "Restore hash mismatch.")
        descriptor = os.open(destination, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        sidecar._fsync_directory(destination.parent)
    finally:
        restore_temp.unlink(missing_ok=True)


def restore_verified_backup(
    backup: Path, destination: Path, expected_hash: str
) -> None:
    """Restore from copies while retaining the only verified backup until validation."""
    sidecar = _facade()
    if not backup.is_file() or sidecar._sha256(backup) != expected_hash:
        raise OSError(errno.EIO, "Verified recovery backup became unavailable.")

    try:
        sidecar._restore_attempt(backup, destination, expected_hash, "restore-primary")
    except BaseException:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        try:
            sidecar._restore_attempt(
                backup, destination, expected_hash, "restore-fallback"
            )
        except BaseException as fallback_error:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            raise SaveAsRecoveryRequiredError(
                destination,
                backup,
                expected_hash,
            ) from fallback_error

    try:
        backup.unlink()
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(destination, backup, expected_hash) from exc


_UNSUPPORTED_EXCHANGE_ERRNOS = {
    errno.EINVAL,
    errno.ENOSYS,
    getattr(errno, "ENOTSUP", errno.EINVAL),
    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
}


def rename_exchange(left: Path, right: Path) -> None:
    """Atomically exchange two same-filesystem names where renameat2 is available."""
    if os.name == "nt":
        raise OSError(errno.ENOTSUP, "rename exchange is unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "rename exchange is unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def replace_existing_with_prior(replacement: Path, destination: Path) -> Path:
    """Install replacement atomically and return the exact displaced destination."""
    sidecar = _facade()
    try:
        sidecar._rename_exchange(replacement, destination)
        return replacement
    except OSError as exc:
        if exc.errno not in _UNSUPPORTED_EXCHANGE_ERRNOS:
            raise
    displaced = sidecar._private_sibling_path(destination, "displaced", ".bak")
    try:
        sidecar.native_dialogs.replace_file_with_backup(
            replacement,
            destination,
            displaced,
        )
    except OSError:
        if displaced.is_file() and destination.is_file() and not replacement.exists():
            return displaced
        raise
    return displaced
