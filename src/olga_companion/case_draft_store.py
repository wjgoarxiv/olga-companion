"""Private storage for case drafts built from a pipe table.

A draft holds a validated CaseSpec v3 while the user reviews and adjusts it. It lives in
private state, never in the workspace, expires after a day, is tied to the workspace
generation it was built in, and is replaced only by an update that names its current
revision. The sidecar is one process, so a process lock serialises updates.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config
from .private_path_acl import harden_private_path
from .sidecar_save_as_fsync import fsync_directory

DRAFT_TTL_SECONDS = 24 * 3600
MAX_DRAFTS = 20
MAX_DRAFT_BYTES = 8 * 1024 * 1024
_IDENTIFIER = re.compile(r"[0-9a-f]{32}")
_LOCK = threading.Lock()


class DraftError(RuntimeError):
    """A draft is missing, expired, from another workspace, stale or unsafe."""


@dataclass(frozen=True)
class Draft:
    draft_id: str
    revision: int
    context_generation: int
    created_at: float
    expires_at: float
    source_name: str
    spec: dict[str, Any]
    summary: dict[str, Any]
    label_map: dict[str, Any]
    options: dict[str, Any]


def _root() -> Path:
    configured = os.environ.get("OLGA_CASE_DRAFT_DIR")
    return Path(configured).expanduser() if configured else config.private_state_root() / "case-drafts"


def _prepare_root() -> Path:
    root = _root()
    if root.is_symlink():
        raise DraftError("The draft folder cannot be a symlink.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    harden_private_path(root, directory=True)
    return root.resolve()


def _path(root: Path, draft_id: str) -> Path:
    if _IDENTIFIER.fullmatch(draft_id) is None:
        raise DraftError("The draft id is not valid.")
    return root / f"{draft_id}.json"


def _write(root: Path, draft: Draft) -> None:
    content = json.dumps(draft.__dict__, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(content) > MAX_DRAFT_BYTES:
        raise DraftError("The draft is too large to keep.")
    handle, temporary = tempfile.mkstemp(prefix=".draft-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        harden_private_path(Path(temporary), directory=False)
        os.replace(temporary, _path(root, draft.draft_id))
        fsync_directory(root)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(root: Path, draft_id: str) -> Draft:
    path = _path(root, draft_id)
    if path.is_symlink() or not path.is_file():
        raise DraftError("The draft was not found; import the table again.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Draft(**data)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise DraftError("The draft record is damaged; import the table again.") from exc


def _prune(root: Path, now: float) -> None:
    # A crashed writer can leave a .draft-*.tmp behind; clear the ones older
    # than the draft TTL. Fresh ones may belong to a writer still in flight.
    for path in root.glob(".draft-*.tmp"):
        if path.is_symlink():
            continue
        try:
            if path.stat().st_mtime <= now - DRAFT_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    drafts = []
    for path in root.glob("*.json"):
        # Only files named like a draft are ever removed; anything else is left alone.
        if _IDENTIFIER.fullmatch(path.stem) is None or path.is_symlink():
            continue
        try:
            draft = _read(root, path.stem)
        except DraftError:
            path.unlink(missing_ok=True)
            continue
        if draft.expires_at <= now:
            path.unlink(missing_ok=True)
        else:
            drafts.append(draft)
    drafts.sort(key=lambda item: (item.created_at, item.draft_id))
    for draft in drafts[: max(0, len(drafts) - MAX_DRAFTS)]:
        _path(root, draft.draft_id).unlink(missing_ok=True)


def create_draft(
    *, context_generation: int, source_name: str, spec: dict[str, Any], summary: dict[str, Any],
    label_map: dict[str, Any], options: dict[str, Any], now: float | None = None,
) -> Draft:
    moment = time.time() if now is None else now
    with _LOCK:
        root = _prepare_root()
        draft = Draft(
            draft_id=secrets.token_hex(16), revision=1, context_generation=context_generation,
            created_at=moment, expires_at=moment + DRAFT_TTL_SECONDS, source_name=source_name,
            spec=spec, summary=summary, label_map=label_map, options=options,
        )
        _write(root, draft)
        _prune(root, moment)
        return draft


def get_draft(draft_id: str, *, context_generation: int, now: float | None = None) -> Draft:
    moment = time.time() if now is None else now
    with _LOCK:
        draft = _read(_prepare_root(), draft_id)
    if draft.expires_at <= moment:
        raise DraftError("The draft has expired; import the table again.")
    if draft.context_generation != context_generation:
        raise DraftError("The draft belongs to another workspace state; import the table again.")
    return draft


def update_draft(
    draft_id: str, *, revision: int, context_generation: int, spec: dict[str, Any],
    summary: dict[str, Any], options: dict[str, Any] | None = None, now: float | None = None,
) -> Draft:
    moment = time.time() if now is None else now
    with _LOCK:
        root = _prepare_root()
        current = _read(root, draft_id)
        if current.expires_at <= moment:
            raise DraftError("The draft has expired; import the table again.")
        if current.context_generation != context_generation:
            raise DraftError("The draft belongs to another workspace state; import the table again.")
        if current.revision != revision:
            raise DraftError("The draft changed since it was read; review it again first.")
        updated = Draft(
            **{**current.__dict__, "revision": revision + 1, "spec": spec, "summary": summary,
               "options": current.options if options is None else options},
        )
        _write(root, updated)
        return updated


def delete_draft(draft_id: str) -> None:
    with _LOCK:
        root = _prepare_root()
        _path(root, draft_id).unlink(missing_ok=True)
