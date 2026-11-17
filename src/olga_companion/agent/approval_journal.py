"""Atomic, restart-safe records for one-shot Chat approvals."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .. import config
from ..sidecar_save_as_fsync import fsync_directory

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{32}")


class ApprovalJournalError(RuntimeError):
    """A journal record could not be read or committed safely."""


def root() -> Path:
    configured = os.environ.get("OLGA_APPROVAL_JOURNAL_DIR")
    return Path(configured) if configured else config.project_root() / "var" / "approval-journal"


PLAN_SUBDIR = "plans"


def _directory(subdir: str) -> Path:
    return root() / subdir if subdir else root()


def _path(pending_id: str, subdir: str = "") -> Path:
    if not _IDENTIFIER.fullmatch(pending_id):
        raise ApprovalJournalError("Approval journal identity is invalid.")
    return _directory(subdir) / f"{pending_id}.json"


def commit(pending_id: str, record: dict[str, Any], subdir: str = "") -> None:
    """Atomically replace one approval record and fsync its directory."""
    directory = _directory(subdir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"version": 1, "pending_id": pending_id, **record},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".approval-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _path(pending_id, subdir))
        fsync_directory(directory)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_all(subdir: str = "") -> dict[str, dict[str, Any]]:
    directory = _directory(subdir)
    if not directory.is_dir():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for path in directory.glob("*.json"):
        if not _IDENTIFIER.fullmatch(path.stem):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(raw, dict)
            and raw.get("version") == 1
            and raw.get("pending_id") == path.stem
        ):
            records[path.stem] = raw
    return records


def load_one(pending_id: str, subdir: str = "") -> dict[str, Any] | None:
    """Read one record by identity; a missing or corrupt file is None."""
    try:
        raw = json.loads(_path(pending_id, subdir).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if isinstance(raw, dict) and raw.get("version") == 1 and raw.get("pending_id") == pending_id:
        return raw
    return None


def clear() -> None:
    for directory in (root(), root() / PLAN_SUBDIR):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            if _IDENTIFIER.fullmatch(path.stem):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
