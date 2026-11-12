"""Atomic private journal for exactly-once case publish receipts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from . import config
from .case_publish_types import PublishJournalRecord
from .sidecar_save_as_fsync import fsync_directory


class PublishJournalError(RuntimeError):
    """A case publication record was missing, malformed, or not durable."""


def root() -> Path:
    configured = os.environ.get("OLGA_CASE_PUBLISH_JOURNAL_DIR")
    return (
        Path(configured).expanduser()
        if configured
        else config.private_state_root() / "case-publish-journal"
    )


def _path(transaction_id: str) -> Path:
    return root() / f"{transaction_id}.json"


def load(transaction_id: str) -> PublishJournalRecord | None:
    path = _path(transaction_id)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        record = PublishJournalRecord.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise PublishJournalError(
            f"Case publish journal is malformed for transaction {transaction_id}."
        ) from exc
    if record.request.transaction_id != transaction_id:
        raise PublishJournalError("Case publish journal identity does not match its file.")
    return record


def commit(record: PublishJournalRecord) -> None:
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise PublishJournalError("Case publish journal root must not be a symlink.")
    payload = json.dumps(
        record.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".case-publish-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _ = os.replace(temporary, _path(record.request.transaction_id))
        fsync_directory(directory)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise
