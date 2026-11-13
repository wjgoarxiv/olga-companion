from __future__ import annotations

from pathlib import Path
from typing import Any


def _facade() -> Any:
    from . import sidecar

    return sidecar


def file_matches(
    path: Path,
    expected_identity: tuple[int, int, int],
    expected_hash: str,
) -> bool:
    """Verify one regular path without following an identity-changing replacement."""
    sidecar = _facade()
    try:
        identity_before = sidecar.save_as_atomic.regular_file_identity(path)
        if identity_before != expected_identity:
            return False
        digest = sidecar._sha256(path)
        identity_after = sidecar.save_as_atomic.regular_file_identity(path)
    except OSError:
        return False
    return identity_after == expected_identity and digest == expected_hash
