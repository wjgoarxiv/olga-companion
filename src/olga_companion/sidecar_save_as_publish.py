from __future__ import annotations

import errno
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from .sidecar_save_as_cleanup import cleanup_existing_private
from .sidecar_save_as_files import SaveAsRecoveryRequiredError
from .sidecar_save_as_identity import file_matches
from .sidecar_save_as_retention import retention_capacity_guard
from .sidecar_save_as_stage import (
    SaveAsValidationError,
    stage_export,
    validate_copy_request,
)


def _facade() -> Any:
    from . import sidecar

    return sidecar


def copy_export_atomic(source: Path, destination: Path) -> int:
    sidecar = _facade()
    parent = validate_copy_request(source, destination)
    destination_initially_exists = destination.exists()
    retention_stack = ExitStack()
    if destination_initially_exists:
        required_retention_bytes = 2 * max(
            source.stat().st_size,
            destination.stat().st_size,
        )
        retention_stack.enter_context(
            retention_capacity_guard(required_retention_bytes)
        )
    temp_path: Path | None = None
    backup_path: Path | None = None
    backup_hash: str | None = None
    backup_identity: tuple[int, int, int] | None = None
    destination_identity: tuple[int, int, int] | None = None
    destination_name_owned = False
    preserve_private_paths = False
    displaced_path: Path | None = None
    try:
        if destination_initially_exists:
            destination_identity = sidecar.save_as_atomic.regular_file_identity(
                destination
            )
            backup_hash = sidecar._sha256(destination)
            backup_path = sidecar._create_verified_backup(destination, backup_hash)
            backup_identity = sidecar.save_as_atomic.regular_file_identity(backup_path)
            if backup_identity is None or not file_matches(
                backup_path,
                backup_identity,
                backup_hash,
            ):
                raise OSError(
                    errno.EIO,
                    "Recovery backup validation failed before Save As staging.",
                )

        staged = stage_export(source, destination, parent)
        temp_path = staged.path
        source_hash = staged.digest
        staged_identity = staged.identity
        size = staged.size
        if destination_initially_exists:
            destination_unchanged = (
                destination_identity is not None
                and backup_hash is not None
                and file_matches(destination, destination_identity, backup_hash)
            )
            if not destination_unchanged:
                preserve_private_paths = True
                raise SaveAsRecoveryRequiredError(
                    destination,
                    backup_path,
                    backup_hash,
                )
        try:
            if destination_initially_exists:
                displaced_path = sidecar._replace_existing_with_prior(
                    temp_path,
                    destination,
                )
                temp_path = None
                destination_name_owned = True
                displaced_hash = sidecar._sha256(displaced_path)
                displaced_is_baseline = (
                    destination_identity is not None
                    and backup_hash is not None
                    and file_matches(
                        displaced_path,
                        destination_identity,
                        backup_hash,
                    )
                )
                if not displaced_is_baseline:
                    discarded = sidecar._restore_displaced(
                        displaced_path,
                        destination,
                        displaced_hash,
                        expected_discarded_identity=staged_identity,
                        expected_discarded_hash=source_hash,
                    )
                    displaced_path = None
                    destination_name_owned = False
                    displaced_path = discarded
                    try:
                        if backup_path is None or backup_identity is None:
                            raise OSError("Verified Save As backup became unavailable.")
                        cleanup_existing_private(
                            destination,
                            displaced_path,
                            staged_identity,
                            source_hash,
                            backup_path,
                            backup_identity,
                            backup_hash,
                        )
                        displaced_path = None
                        backup_path = None
                    except SaveAsRecoveryRequiredError:
                        preserve_private_paths = True
                        raise
                    except OSError as exc:
                        if backup_path is not None and backup_hash is not None:
                            preserve_private_paths = True
                            raise SaveAsRecoveryRequiredError(
                                destination,
                                backup_path,
                                backup_hash,
                            ) from exc
                        raise sidecar.save_as_atomic.SaveAsPublishUncertainError(
                            destination
                        ) from exc
                    raise SaveAsValidationError(
                        "Selected destination changed during Save As; "
                        "the concurrent file was preserved."
                    )
                sidecar._fsync_directory(parent)
                destination_matches = file_matches(
                    destination,
                    staged_identity,
                    source_hash,
                )
                if (
                    destination_identity is None
                    or backup_path is None
                    or backup_identity is None
                    or backup_hash is None
                ):
                    preserve_private_paths = True
                    raise SaveAsRecoveryRequiredError(
                        destination,
                        backup_path or displaced_path,
                        backup_hash or displaced_hash,
                    )
                try:
                    cleanup_existing_private(
                        destination,
                        displaced_path,
                        destination_identity,
                        backup_hash,
                        backup_path,
                        backup_identity,
                        backup_hash,
                    )
                except SaveAsRecoveryRequiredError:
                    preserve_private_paths = True
                    raise
                displaced_path = None
                backup_path = None
                if not destination_matches:
                    raise sidecar.save_as_atomic.SaveAsConcurrentDestinationError(
                        destination
                    )
                if not file_matches(destination, staged_identity, source_hash):
                    raise sidecar.save_as_atomic.SaveAsConcurrentDestinationError(
                        destination
                    )
            else:
                try:
                    sidecar.save_as_atomic.publish_absent_no_clobber(
                        temp_path,
                        destination,
                        sidecar._fsync_directory,
                    )
                except FileExistsError as exc:
                    raise SaveAsValidationError(
                        "Selected destination was created by another process; "
                        "its file was preserved."
                    ) from exc
                temp_path = None
                destination_name_owned = True
        except SaveAsRecoveryRequiredError:
            preserve_private_paths = True
            raise
        except sidecar.save_as_atomic.SaveAsPublishUncertainError:
            raise
        except (OSError, ValueError) as exc:
            if (
                destination_name_owned
                and backup_path is not None
                and backup_hash is not None
            ):
                preserve_private_paths = True
                raise SaveAsRecoveryRequiredError(
                    destination,
                    backup_path,
                    backup_hash,
                ) from exc
            if destination_name_owned:
                raise sidecar.save_as_atomic.SaveAsPublishUncertainError(
                    destination
                ) from exc
            raise
        return size
    finally:
        retention_stack.close()
        suppress_cleanup_errors = sys.exc_info()[0] is not None
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                if not suppress_cleanup_errors:
                    raise
        allow_exception_cleanup = (
            not suppress_cleanup_errors or not destination_name_owned
        )
        if (
            displaced_path is not None
            and not preserve_private_paths
            and allow_exception_cleanup
        ):
            try:
                displaced_path.unlink(missing_ok=True)
            except OSError:
                if not suppress_cleanup_errors:
                    raise
        if (
            backup_path is not None
            and not preserve_private_paths
            and allow_exception_cleanup
        ):
            try:
                backup_path.unlink(missing_ok=True)
            except OSError:
                if not suppress_cleanup_errors:
                    raise
