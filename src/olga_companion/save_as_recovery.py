"""Durable private records for retained Save As recovery backups."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .private_path_acl import harden_private_path

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCK = threading.Lock()


class RecoveryNotFoundError(LookupError):
    """The opaque recovery id is invalid, unknown, or its record is malformed."""


def _root() -> Path:
    return config.private_state_root() / "save-as-recovery"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_private_root() -> Path:
    root = _root()
    if root.is_symlink():
        raise OSError("Recovery record directory must not be a symlink.")
    created = not root.exists()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    harden_private_path(root, directory=True)
    if created:
        config._fsync_parent_directory(root.parent)
    return root


def persist(destination: Path, backup: Path, expected_hash: str) -> str:
    """Atomically persist a path-bearing private record before publishing its id."""
    destination = destination.expanduser().resolve()
    backup = backup.expanduser().resolve()
    if not _HASH_RE.fullmatch(expected_hash):
        raise OSError("Recovery hash is invalid.")
    if not backup.is_file() or _sha256(backup) != expected_hash:
        raise OSError("Verified recovery backup is unavailable.")
    recovery_id = secrets.token_urlsafe(18)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "id": recovery_id,
        "destination": str(destination),
        "backup": str(backup),
        "expected_hash": expected_hash,
        "timestamp": timestamp,
    }
    with _LOCK:
        root = _prepare_private_root()
        target = root / f"{recovery_id}.json"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".recovery-",
                suffix=".tmp",
                dir=root,
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(record, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            harden_private_path(temp_path, directory=False)
            os.replace(temp_path, target)
            temp_path = None
            try:
                harden_private_path(target, directory=False)
            except OSError:
                target.unlink(missing_ok=True)
                config._fsync_parent_directory(root)
                raise
            config._fsync_parent_directory(root)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return recovery_id


def _read_record(recovery_id: str) -> dict[str, Any]:
    if not isinstance(recovery_id, str) or not _ID_RE.fullmatch(recovery_id):
        raise RecoveryNotFoundError(recovery_id)
    try:
        path = _prepare_private_root() / f"{recovery_id}.json"
        harden_private_path(path, directory=False)
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryNotFoundError(recovery_id) from exc
    if not isinstance(record, dict) or set(record) != {
        "id",
        "destination",
        "backup",
        "expected_hash",
        "timestamp",
    }:
        raise RecoveryNotFoundError(recovery_id)
    if record.get("id") != recovery_id:
        raise RecoveryNotFoundError(recovery_id)
    if not all(isinstance(record.get(key), str) and record[key] for key in record):
        raise RecoveryNotFoundError(recovery_id)
    if not _HASH_RE.fullmatch(record["expected_hash"]):
        raise RecoveryNotFoundError(recovery_id)
    return record


def status(recovery_id: str) -> dict[str, Any]:
    """Return actionable redacted status; never return either private path."""
    with _LOCK:
        record = _read_record(recovery_id)
    backup = Path(record["backup"])
    try:
        available = backup.is_file() and _sha256(backup) == record["expected_hash"]
    except OSError:
        available = False
    return {
        "id": recovery_id,
        "status": "available" if available else "missing",
        "basename": Path(record["destination"]).name,
        "backup_available": available,
        "time": record["timestamp"],
    }
