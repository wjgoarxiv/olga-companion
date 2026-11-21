from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from .sidecar_save_as_files import (
    SaveAsRecoveryRequiredError,
    private_sibling_path,
)
from .sidecar_save_as_identity import file_matches
from .sidecar_save_as_retention import allocate_retention_root
from .private_path_acl import harden_private_path


class _CaptureHardeningError(OSError):
    def __init__(self, captured: Path) -> None:
        self.captured = captured
        super().__init__("Save As retained-file privacy could not be verified.")


def _regular_file_size(path: Path) -> int:
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(errno.EINVAL, "Save As private entry is not a regular file.")
    return metadata.st_size


def _capture_owned_name(
    path: Path,
    expected_identity: tuple[int, int, int],
    expected_hash: str,
    retention_root: Path,
) -> Path | None:
    """Atomically remove a public private-file name before validating its target."""
    captured = private_sibling_path(
        retention_root / path.name,
        "cleanup",
        path.suffix or ".tmp",
    )
    try:
        os.replace(path, captured)
    except OSError:
        return None
    try:
        harden_private_path(captured, directory=False)
    except OSError as exc:
        raise _CaptureHardeningError(captured) from exc
    matches = file_matches(captured, expected_identity, expected_hash)
    if path.exists():
        return None
    if not matches:
        try:
            os.link(captured, path)
        except FileExistsError:
            return None
        except OSError:
            return None
        # The entry is foreign. Keep the captured link because the restored name
        # can be replaced concurrently before any later unlink.
        return None
    return captured


def cleanup_existing_private(
    destination: Path,
    displaced: Path,
    displaced_identity: tuple[int, int, int],
    displaced_hash: str,
    backup: Path,
    backup_identity: tuple[int, int, int],
    backup_hash: str,
) -> None:
    """Retire known private names without deleting through mutable pathnames."""
    try:
        required_bytes = _regular_file_size(displaced) + _regular_file_size(backup)
        retention_root = allocate_retention_root(destination, required_bytes)
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(destination, backup, backup_hash) from exc
    try:
        captured_displaced = _capture_owned_name(
            displaced,
            displaced_identity,
            displaced_hash,
            retention_root,
        )
    except _CaptureHardeningError as exc:
        raise SaveAsRecoveryRequiredError(
            destination,
            backup,
            backup_hash,
        ) from exc
    if captured_displaced is None:
        raise SaveAsRecoveryRequiredError(destination, backup, backup_hash)

    try:
        captured_backup = _capture_owned_name(
            backup,
            backup_identity,
            backup_hash,
            retention_root,
        )
    except _CaptureHardeningError as exc:
        raise SaveAsRecoveryRequiredError(
            destination,
            exc.captured,
            backup_hash,
        ) from exc
    if captured_backup is None:
        recovery = (
            backup
            if file_matches(backup, backup_identity, backup_hash)
            else captured_displaced
        )
        raise SaveAsRecoveryRequiredError(destination, recovery, backup_hash)
