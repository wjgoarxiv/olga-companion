"""Versioned, append-only canonical Chat transcript persistence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import config
from . import history_listing
from .history_listing import SessionMeta
from .history_policy import sanitize_record

_SESSION_ID = re.compile(r"[a-f0-9]{12,32}")
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}


class ChatHistoryError(ValueError):
    """A Chat session identity or persistence transition is invalid."""


class ChatHistoryCorruptionError(ChatHistoryError):
    """A malformed non-terminal JSONL record makes replay unsafe."""


def _valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID.fullmatch(session_id))


def chats_root() -> Path:
    root = config.project_root() / "var" / "chats"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_path(session_id: str) -> Path:
    if not _valid_session_id(session_id):
        raise ChatHistoryError(f"Invalid session id: {session_id!r}")
    return chats_root() / f"{session_id}.jsonl"


def _path_lock(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(path.resolve(), threading.RLock())


def delete(session_id: str) -> bool:
    """Physically remove task-owned history; the HTTP UI uses ``detach``."""
    path = _session_path(session_id)
    with _path_lock(path):
        if path.exists():
            path.unlink()
            history_listing.remove(path)
            return True
        return False


def detach(session_id: str) -> bool:
    """Append a tombstone so UI deletion never affects referenced simulations."""
    path = _session_path(session_id)
    with _path_lock(path):
        if not path.exists():
            return False
        records = read(session_id)
        if records and records[-1].get("record") == "tombstone":
            return False
        append(session_id, {"record": "tombstone", "state": "detached"})
        return True


def new_session(title: str = "") -> str:
    session_id = uuid.uuid4().hex[:16]
    path = _session_path(session_id)
    record = _canonical_record(
        {"record": "meta", "session_id": session_id, "title": title[:200]},
        sequence=0,
    )
    with _path_lock(path), path.open("x", encoding="utf-8") as handle:
        handle.write(_encode(record))
        handle.flush()
        os.fsync(handle.fileno())
    history_listing.touch(path, title=title[:200])
    return session_id


def tool_result_record_id(call_id: str) -> str:
    """Stable id for the one answer a call may have; `append` skips a repeat atomically."""
    return f"tool_result:{call_id}"


def append(session_id: str, record: dict[str, Any]) -> None:
    """Append one sanitized canonical record under a process-wide path lock."""
    path = _session_path(session_id)
    normalized = json.loads(json.dumps(record, default=str))
    with _path_lock(path):
        if not path.exists():
            raise ChatHistoryError(f"Unknown session: {session_id}")
        raw_records = _read_raw(path, repair_final=True)
        requested_id = normalized.get("record_id")
        if requested_id and any(
            item.get("record_id") == requested_id for item in raw_records
        ):
            return
        canonical = _canonical_record(normalized, sequence=len(raw_records))
        encoded = _encode(canonical)
        if raw_records[-1:] and raw_records[-1].get("record") == "tombstone" and canonical.get("record") != "tombstone":
            # A turn still running when its chat was deleted keeps its records (approval
            # and terminal receipts must not be lost), but the chat has to stay deleted.
            encoded += _encode(
                _canonical_record({"record": "tombstone", "state": "detached"}, sequence=len(raw_records) + 1)
            )
        payload = encoded.encode("utf-8")
        initial_size = path.stat().st_size
        descriptor = os.open(path, os.O_APPEND | os.O_WRONLY)
        try:
            written = os.write(descriptor, payload)
            if written != len(payload):
                message = "Chat history append was incomplete."
                raise OSError(message)
            os.fsync(descriptor)
        except OSError:
            try:
                os.ftruncate(descriptor, initial_size)
                os.fsync(descriptor)
            except OSError as rollback_error:
                raise ChatHistoryCorruptionError(
                    "Chat history append failed and could not be rolled back."
                ) from rollback_error
            raise
        finally:
            os.close(descriptor)
        if normalized.get("record") == "tombstone":
            history_listing.remove(path)
        else:
            history_listing.touch(path)


def read(session_id: str) -> list[dict[str, Any]]:
    path = _session_path(session_id)
    if not path.exists():
        raise ChatHistoryError(f"Unknown session: {session_id}")
    with _path_lock(path):
        raw_records = _read_raw(path)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    prior_legacy: dict[str, Any] | None = None
    for index, raw in enumerate(raw_records):
        explicit_id = raw.get("record_id")
        if isinstance(explicit_id, str) and explicit_id in seen_ids:
            continue
        if _is_legacy_double_assistant(raw, prior_legacy):
            continue
        record = _canonical_record(raw, sequence=len(records), legacy_index=index)
        seen_ids.add(str(record["record_id"]))
        records.append(record)
        prior_legacy = raw if "record_id" not in raw else None
    return records


def list_sessions() -> list[SessionMeta]:
    return history_listing.list_sessions(chats_root())


def iter_turns(session_id: str) -> Iterator[dict[str, Any]]:
    """Yield only the user/assistant turns (for rebuilding conversation context)."""
    for rec in read(session_id):
        if rec.get("record") in {"user", "assistant"}:
            yield rec


def _read_raw(
    path: Path, *, repair_final: bool = False
) -> list[dict[str, Any]]:
    raw_bytes = path.read_bytes()
    entries: list[tuple[int, bytes]] = []
    offset = 0
    for line in raw_bytes.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            entries.append((offset, stripped))
        offset += len(line)
    records: list[dict[str, Any]] = []
    for index, (line_offset, encoded) in enumerate(entries):
        try:
            records.append(json.loads(encoded.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if index != len(entries) - 1:
                raise ChatHistoryCorruptionError(
                    "Chat history contains a malformed middle record."
                ) from exc
            if repair_final:
                with path.open("r+b") as handle:
                    handle.truncate(line_offset)
                    handle.flush()
                    os.fsync(handle.fileno())
            break
    else:
        if repair_final and raw_bytes and not raw_bytes.endswith((b"\n", b"\r")):
            with path.open("ab") as handle:
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
    return records


def _canonical_record(
    raw: dict[str, Any], *, sequence: int, legacy_index: int | None = None
) -> dict[str, Any]:
    sanitized = sanitize_record(raw)
    record_id = sanitized.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        if legacy_index is None:
            record_id = uuid.uuid4().hex
        else:
            digest = hashlib.sha256(
                json.dumps(sanitized, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            record_id = f"legacy-{legacy_index}-{digest[:20]}"
    return {
        **sanitized,
        "schema_version": 1,
        "sequence": sequence,
        "record_id": record_id,
    }


def _is_legacy_double_assistant(
    record: dict[str, Any], prior: dict[str, Any] | None
) -> bool:
    return bool(
        prior is not None
        and "record_id" not in record
        and record.get("record") == "assistant"
        and prior.get("record") == "assistant"
        and record.get("text") == prior.get("text")
    )


def _encode(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
