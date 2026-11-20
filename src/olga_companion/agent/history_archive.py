"""Recoverable archival for empty and explicitly marked QA Chat sessions."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .. import config
from . import history, history_listing


@dataclass(frozen=True, slots=True)
class ArchiveItem:
    session_id: str
    reason: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ArchivePlan:
    created_at: str
    source_root: str
    items: tuple[ArchiveItem, ...]


@dataclass(frozen=True, slots=True)
class ArchiveReceipt:
    archive_id: str
    manifest_path: Path
    moved: int


def build_archive_plan() -> ArchivePlan:
    root = history.chats_root()
    items: list[ArchiveItem] = []
    for path in sorted(root.glob("*.jsonl")):
        try:
            records = history.read(path.stem)
        except (OSError, ValueError):
            continue
        reason = _archive_reason(records)
        if reason is None:
            continue
        items.append(
            ArchiveItem(
                session_id=path.stem,
                reason=reason,
                sha256=_hash(path),
                size=path.stat().st_size,
            )
        )
    return ArchivePlan(
        created_at=datetime.now(UTC).isoformat(),
        source_root=str(root.resolve()),
        items=tuple(items),
    )


def write_dry_run_manifest(
    plan: ArchivePlan, destination: Path | None = None
) -> Path:
    target = destination or (
        config.project_root() / "var" / "chat-archives" / "dry-run-manifest.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(target, _plan_payload(plan, state="dry-run"))
    return target


def apply_archive_plan(
    plan: ArchivePlan, *, archive_id: str | None = None
) -> ArchiveReceipt:
    source_root = history.chats_root().resolve()
    if source_root != Path(plan.source_root):
        raise ValueError("Archive plan source no longer matches the active Chat root.")
    resolved_id = archive_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_root = config.project_root() / "var" / "chat-archives" / resolved_id
    sessions_root = archive_root / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=False)

    moved: list[ArchiveItem] = []
    try:
        for item in plan.items:
            source = source_root / f"{item.session_id}.jsonl"
            if not source.exists() or _hash(source) != item.sha256:
                raise ValueError(f"Session changed after dry-run: {item.session_id}")
            destination = sessions_root / source.name
            shutil.move(str(source), str(destination))
            moved.append(item)
        manifest = archive_root / "manifest.json"
        _atomic_json(
            manifest,
            {
                **_plan_payload(plan, state="archived"),
                "archive_id": resolved_id,
                "moved": len(moved),
            },
        )
    except Exception:
        for item in reversed(moved):
            archived = sessions_root / f"{item.session_id}.jsonl"
            if archived.exists():
                shutil.move(str(archived), str(source_root / archived.name))
        raise
    history_listing.invalidate(source_root)
    return ArchiveReceipt(resolved_id, manifest, len(moved))


def restore_archive(manifest_path: Path) -> int:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = Path(str(payload["source_root"]))
    sessions_root = manifest_path.parent / "sessions"
    restored = 0
    for raw in payload["items"]:
        item = ArchiveItem(**raw)
        archived = sessions_root / f"{item.session_id}.jsonl"
        destination = source_root / archived.name
        if destination.exists():
            raise FileExistsError(f"Restore target already exists: {destination}")
        if not archived.exists() or _hash(archived) != item.sha256:
            raise ValueError(f"Archived session failed hash validation: {item.session_id}")
        shutil.move(str(archived), str(destination))
        restored += 1
    history_listing.invalidate(source_root)
    return restored


def _archive_reason(records: list[dict[str, object]]) -> str | None:
    turns = [record for record in records if record.get("record") == "user"]
    if not turns:
        return "metadata-only"
    meta = records[0] if records else {}
    title = str(meta.get("title", "")).strip().casefold()
    explicitly_marked = title.startswith("[qa]") or any(
        record.get("qa_session") is True for record in records
    )
    return "explicit-qa" if explicitly_marked else None


def _plan_payload(plan: ArchivePlan, *, state: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "state": state,
        "created_at": plan.created_at,
        "source_root": plan.source_root,
        "items": [asdict(item) for item in plan.items],
    }


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
