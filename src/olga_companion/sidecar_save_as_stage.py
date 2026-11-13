from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SaveAsValidationError(ValueError):
    """A Save As request cannot be published without violating its safety contract."""


@dataclass(frozen=True, slots=True)
class StagedExport:
    path: Path
    digest: str
    identity: tuple[int, int, int]
    size: int


def _facade() -> Any:
    from . import sidecar

    return sidecar


def validate_copy_request(source: Path, destination: Path) -> Path:
    if destination.suffix.casefold() != source.suffix.casefold():
        raise SaveAsValidationError(
            f"Selected destination must use the {source.suffix.lower()} extension."
        )
    if destination.resolve() == source.resolve():
        raise SaveAsValidationError(
            "Export source and destination must be different files."
        )
    if destination.exists() and os.path.samefile(source, destination):
        raise SaveAsValidationError(
            "Export source and destination must not refer to the same file."
        )
    parent = destination.parent
    if not parent.is_dir():
        raise SaveAsValidationError("Selected destination parent does not exist.")
    return parent


def stage_export(source: Path, destination: Path, parent: Path) -> StagedExport:
    sidecar = _facade()
    source_hash = sidecar._sha256(source)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            with source.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        if (
            sidecar._sha256(source) != source_hash
            or sidecar._sha256(temp_path) != source_hash
        ):
            raise SaveAsValidationError(
                "Export source changed during Save As; no destination was written."
            )
        identity = sidecar.save_as_atomic.regular_file_identity(temp_path)
        if identity is None:
            raise SaveAsValidationError("Save As staging path is not a regular file.")
        return StagedExport(temp_path, source_hash, identity, temp_path.stat().st_size)
    except BaseException:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
