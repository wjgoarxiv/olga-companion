"""Bounded metadata inventory for canonical Chat history."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import TypedDict


class SessionMeta(TypedDict):
    session_id: str
    title: str
    updated_ms: int


_CACHE_GUARD = threading.RLock()
_CACHE_ROOT: Path | None = None
_CACHE: list[tuple[int, SessionMeta]] | None = None
_CACHE_DIRECTORY_SIGNATURE: tuple[int | None, tuple[str, ...]] | None = None


def list_sessions(root: Path) -> list[SessionMeta]:
    global _CACHE_ROOT, _CACHE, _CACHE_DIRECTORY_SIGNATURE

    resolved_root = root.resolve()
    directory_signature = _directory_signature(root)
    with _CACHE_GUARD:
        if (
            _CACHE_ROOT == resolved_root
            and _CACHE is not None
            and _CACHE_DIRECTORY_SIGNATURE == directory_signature
        ):
            return [_copy_session(session) for _, session in _CACHE]

        indexed: list[tuple[int, SessionMeta]] = []
        for path in root.glob("*.jsonl"):
            try:
                modified_ns = path.stat().st_mtime_ns
                meta, tail = _listing_records(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if tail.get("record") == "tombstone":
                continue
            indexed.append(
                (
                    modified_ns,
                    {
                        "session_id": path.stem,
                        "title": str(meta.get("title", "")),
                        "updated_ms": modified_ns // 1_000_000,
                    },
                )
            )
        indexed.sort(key=lambda item: (item[0], item[1]["session_id"]), reverse=True)
        _CACHE_ROOT = resolved_root
        _CACHE = indexed
        _CACHE_DIRECTORY_SIGNATURE = _directory_signature(root)
        return [_copy_session(session) for _, session in indexed]


def remove(path: Path) -> None:
    global _CACHE_DIRECTORY_SIGNATURE

    root = path.parent.resolve()
    with _CACHE_GUARD:
        if _CACHE_ROOT != root or _CACHE is None:
            return
        _CACHE[:] = [
            item for item in _CACHE if item[1]["session_id"] != path.stem
        ]
        _CACHE_DIRECTORY_SIGNATURE = _directory_signature(path.parent)


def touch(path: Path, *, title: str | None = None) -> None:
    global _CACHE_DIRECTORY_SIGNATURE

    root = path.parent.resolve()
    with _CACHE_GUARD:
        if _CACHE_ROOT != root or _CACHE is None:
            return
        existing = next(
            (
                session
                for _, session in _CACHE
                if session["session_id"] == path.stem
            ),
            None,
        )

    resolved_title = title
    if resolved_title is None:
        if existing is not None:
            resolved_title = existing["title"]
        else:
            try:
                meta, tail = _listing_records(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return
            if tail.get("record") == "tombstone":
                remove(path)
                return
            resolved_title = str(meta.get("title", ""))

    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        remove(path)
        return

    with _CACHE_GUARD:
        if _CACHE_ROOT != root or _CACHE is None:
            return
        if _CACHE:
            modified_ns = max(modified_ns, _CACHE[0][0] + 1)
        session: SessionMeta = {
            "session_id": path.stem,
            "title": resolved_title,
            "updated_ms": modified_ns // 1_000_000,
        }
        _CACHE[:] = [
            item for item in _CACHE if item[1]["session_id"] != path.stem
        ]
        _CACHE.append((modified_ns, session))
        _CACHE.sort(
            key=lambda item: (item[0], item[1]["session_id"]), reverse=True
        )
        _CACHE_DIRECTORY_SIGNATURE = _directory_signature(path.parent)


def invalidate(root: Path) -> None:
    global _CACHE_ROOT, _CACHE, _CACHE_DIRECTORY_SIGNATURE

    with _CACHE_GUARD:
        if _CACHE_ROOT == root.resolve():
            _CACHE_ROOT = None
            _CACHE = None
            _CACHE_DIRECTORY_SIGNATURE = None


def _directory_signature(root: Path) -> tuple[int | None, tuple[str, ...]]:
    try:
        with os.scandir(root) as entries:
            names = tuple(
                sorted(
                    entry.name
                    for entry in entries
                    if entry.is_file(follow_symlinks=False)
                    and entry.name.endswith(".jsonl")
                )
            )
        return root.stat().st_mtime_ns, names
    except OSError:
        return None, ()


def _listing_records(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    with path.open("rb") as handle:
        first_line = handle.readline().decode("utf-8").strip()
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        tail_start = max(0, end - 4096)
        handle.seek(tail_start)
        tail_bytes = handle.read().rstrip(b"\r\n")
    meta = json.loads(first_line) if first_line else {}
    boundary = tail_bytes.rfind(b"\n")
    if boundary < 0 and tail_start > 0:
        return meta, {}
    tail_line = tail_bytes[boundary + 1 :] if boundary >= 0 else tail_bytes
    try:
        tail = json.loads(tail_line.decode("utf-8")) if tail_line else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        tail = {}
    return meta, tail


def _copy_session(session: SessionMeta) -> SessionMeta:
    return {
        "session_id": session["session_id"],
        "title": session["title"],
        "updated_ms": session["updated_ms"],
    }
