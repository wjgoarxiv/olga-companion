"""Name a run by the approved change behind the case it used.

A case is linked to a change only through a completed publish receipt whose published hash equals the
hash of the case the run used. A hand-made case, a planned but unapproved edit or an unreadable record
has no change, and nothing is guessed from file names.
"""

from __future__ import annotations

import json

from . import case_publish_journal, case_transaction_store
from .case_publish_journal import PublishJournalError

_MAX_RECORDS = 2000
_MAX_CHANGES_BYTES = 256 * 1024


def _changes(transaction_id: str) -> dict | None:
    try:
        path = case_transaction_store.changes_path(transaction_id)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_CHANGES_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, case_transaction_store.TransactionStoreError):
        return None
    if not isinstance(raw, dict):
        return None
    name, changes = raw.get("source_name"), raw.get("changes")
    if not (name is None or isinstance(name, str)) or not isinstance(changes, list) or not changes:
        return None
    if not all(isinstance(item, dict) and isinstance(item.get("path"), str) and {"before", "after"} <= item.keys() for item in changes):
        return None
    return {"source_name": name, "changes": [
        {"path": item["path"], "before": item["before"], "after": item["after"],
         **({"unit": item["unit"]} if isinstance(item.get("unit"), str) else {})}
        for item in changes
    ]}


def approved_changes_by_hash() -> dict[str, dict]:
    """Published case hash -> the source name and the change list that was approved for it."""
    root = case_publish_journal.root()
    if not root.is_dir() or root.is_symlink():
        return {}
    files = sorted(
        (path for path in root.glob("*.json") if path.is_file() and not path.is_symlink()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )[:_MAX_RECORDS]
    index: dict[str, dict] = {}
    for path in files:
        try:
            record = case_publish_journal.load(path.stem)
        except PublishJournalError:
            continue
        if record is None or record.state != "completed" or record.receipt is None:
            continue
        found = _changes(record.request.transaction_id)
        if found is not None:
            index.setdefault(record.receipt.published_hash, found)
    return index
