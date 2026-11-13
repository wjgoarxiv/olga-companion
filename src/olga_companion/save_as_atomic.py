from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar


class SaveAsPublishUncertainError(OSError):
    """A destination was published, but its final durability is uncertain."""

    code: ClassVar[str] = "save_as_publish_uncertain"
    public_message: ClassVar[str] = (
        "Save As published the selected file, but final durability could not be verified."
    )

    def __init__(self, destination: Path) -> None:
        self.destination = destination
        super().__init__(self.public_message)


class SaveAsConcurrentDestinationError(SaveAsPublishUncertainError):
    """The destination changed after its no-clobber publication."""

    code: ClassVar[str] = "save_as_concurrent_destination"
    public_message: ClassVar[str] = (
        "Save As detected that the selected destination changed during publication."
    )


def _sha256(path: Path) -> bytes:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").digest()


def regular_file_identity(path: Path) -> tuple[int, int, int] | None:
    """Return a non-following portable identity, or None for a non-regular file."""
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        return None
    inode = getattr(metadata, "st_ino", 0)
    fallback = 0 if inode else getattr(metadata, "st_ctime_ns", 0)
    return getattr(metadata, "st_dev", 0), inode, fallback


def _matches_published_file(
    destination: Path,
    expected_identity: tuple[int, int, int],
    expected_digest: bytes,
) -> bool:
    identity_before = regular_file_identity(destination)
    if identity_before != expected_identity:
        return False
    digest = _sha256(destination)
    identity_after = regular_file_identity(destination)
    return identity_after == expected_identity and digest == expected_digest


def publish_absent_no_clobber(
    temp_path: Path,
    destination: Path,
    fsync_directory: Callable[[Path], None],
) -> None:
    """Publish once, verify the linked bytes, and never roll back the shared name."""
    expected_identity = regular_file_identity(temp_path)
    if expected_identity is None:
        raise OSError("Save As staging path is not a regular file.")
    expected_digest = _sha256(temp_path)
    os.link(temp_path, destination)
    verification_error: OSError | None = None
    try:
        fsync_directory(destination.parent)
    except OSError as exc:
        verification_error = exc
    try:
        temp_path.unlink(missing_ok=True)
    except OSError as exc:
        raise SaveAsPublishUncertainError(destination) from exc
    if verification_error is not None:
        raise SaveAsPublishUncertainError(destination) from verification_error
    try:
        published_matches = _matches_published_file(
            destination,
            expected_identity,
            expected_digest,
        )
    except OSError as exc:
        raise SaveAsPublishUncertainError(destination) from exc
    if not published_matches:
        raise SaveAsConcurrentDestinationError(destination)
