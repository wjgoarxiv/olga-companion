from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from .sidecar_save_as_files import SaveAsRecoveryRequiredError
from .sidecar_save_as_identity import file_matches


def _facade() -> Any:
    from . import sidecar

    return sidecar


def _retain_winner_recovery(
    destination: Path,
    expected_hash: str,
) -> SaveAsRecoveryRequiredError:
    sidecar = _facade()
    try:
        recovery = sidecar._create_verified_backup(destination, expected_hash)
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(
            destination,
            destination,
            expected_hash,
        ) from exc
    return SaveAsRecoveryRequiredError(destination, recovery, expected_hash)


def _restore_latest_winner(
    discarded: Path,
    destination: Path,
    first_recovery: Path,
    first_hash: str,
) -> NoReturn:
    sidecar = _facade()
    try:
        latest_identity = sidecar.save_as_atomic.regular_file_identity(discarded)
        if latest_identity is None:
            raise OSError("Latest concurrent destination is not a regular file.")
        latest_hash = sidecar._sha256(discarded)
        latest_recovery = sidecar._create_verified_backup(discarded, latest_hash)
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(
            destination,
            first_recovery,
            first_hash,
        ) from exc
    try:
        sidecar._replace_existing_with_prior(discarded, destination)
        if not file_matches(destination, latest_identity, latest_hash):
            raise OSError("Latest concurrent destination restore validation failed.")
        sidecar._fsync_directory(destination.parent)
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(
            destination,
            latest_recovery,
            latest_hash,
        ) from exc
    raise SaveAsRecoveryRequiredError(
        destination,
        first_recovery,
        first_hash,
    )


def restore_displaced(
    displaced: Path,
    destination: Path,
    expected_hash: str,
    *,
    expected_discarded_identity: tuple[int, int, int] | None = None,
    expected_discarded_hash: str | None = None,
) -> Path:
    """Restore the displaced concurrent file and return the discarded replacement."""
    sidecar = _facade()
    try:
        recovery = sidecar._create_verified_backup(displaced, expected_hash)
    except OSError as exc:
        try:
            displaced_is_valid = (
                displaced.is_file() and sidecar._sha256(displaced) == expected_hash
            )
        except OSError:
            displaced_is_valid = False
        if displaced_is_valid:
            raise SaveAsRecoveryRequiredError(
                destination,
                displaced,
                expected_hash,
            ) from exc
        raise
    try:
        discarded = sidecar._replace_existing_with_prior(displaced, destination)
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(destination, recovery, expected_hash) from exc
    if (
        expected_discarded_identity is not None
        and expected_discarded_hash is not None
        and not file_matches(
            discarded,
            expected_discarded_identity,
            expected_discarded_hash,
        )
    ):
        _restore_latest_winner(
            discarded,
            destination,
            recovery,
            expected_hash,
        )
    try:
        if sidecar._sha256(destination) != expected_hash:
            raise SaveAsRecoveryRequiredError(destination, recovery, expected_hash)
        sidecar._fsync_directory(destination.parent)
    except SaveAsRecoveryRequiredError:
        raise
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(destination, recovery, expected_hash) from exc
    try:
        sidecar._fsync_directory(destination.parent)
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(
            destination,
            recovery,
            expected_hash,
        ) from exc
    try:
        recovery.unlink()
    except OSError as exc:
        raise SaveAsRecoveryRequiredError(destination, recovery, expected_hash) from exc
    try:
        sidecar._fsync_directory(destination.parent)
    except OSError as exc:
        raise _retain_winner_recovery(destination, expected_hash) from exc
    return discarded
