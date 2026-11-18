from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .genkey_static import OlgaInputError


@dataclass(frozen=True, slots=True)
class ResultSourceChangedError(OlgaInputError):
    """A result source no longer matches the digest bound to an operation."""

    path: Path
    sha256_before: str
    sha256_after: str | None

    def __str__(self) -> str:
        return "Result source changed while it was being read. Wait for OLGA to finish writing, then retry."


def ensure_result_source_unchanged(
    path: Path,
    sha256_before: str,
    hash_file: Callable[[Path], str],
    *,
    discard_root: Path | None = None,
) -> str:
    """Compute one final digest and reject any moving or vanished source."""
    try:
        sha256_after = hash_file(path)
    except OSError as exc:
        if discard_root is not None:
            shutil.rmtree(discard_root, ignore_errors=True)
        raise ResultSourceChangedError(path, sha256_before, None) from exc
    if sha256_after != sha256_before:
        if discard_root is not None:
            shutil.rmtree(discard_root, ignore_errors=True)
        raise ResultSourceChangedError(path, sha256_before, sha256_after)
    return sha256_after
