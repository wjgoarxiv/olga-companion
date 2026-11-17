"""Approval-gated copy of a chosen .tab to the exact reference name a case expects.

A run stages each PVTFILE from the case (.genkey) folder. When the case names a table that is
not there, the user may copy a workspace .tab next to the case under the referenced relative
name. The copy happens only with a single-use approval token bound to this exact request, never
overwrites, never leaves the case folder, and is verified by sha256 after the write.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from . import workspace
from .agent import approvals
from .run_companions import companion_references

ACTION_KIND = "run_companion_copy"
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_FORBIDDEN_CHARS = re.compile(r'[\x00-\x1f<>:"|?*]')


class RunCompanionCopyError(ValueError):
    """The copy was refused; nothing was written."""


def _relative_parts(reference: str) -> list[str]:
    text = reference.strip()
    if not text:
        raise RunCompanionCopyError("The case does not name the table file.")
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_PREFIX.match(normalized):
        raise RunCompanionCopyError(
            "An absolute table reference cannot be copied; change the case to a name next to it."
        )
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts:
        raise RunCompanionCopyError("The case does not name the table file.")
    if ".." in parts:
        raise RunCompanionCopyError("A table reference that leaves the case folder cannot be copied.")
    if _FORBIDDEN_CHARS.search("".join(parts)):
        raise RunCompanionCopyError("The table reference contains characters a file name cannot have.")
    if not parts[-1].casefold().endswith(".tab"):
        raise RunCompanionCopyError("Only a .tab reference can be fixed by copying a table.")
    return parts


def _display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def plan(*, source: str, reference: str, tab_source: str) -> dict[str, Any]:
    """Validate one copy and describe it; every refusal here happens before anything is written."""
    try:
        genkey = workspace.resolve_input_file(source, {".genkey"})
        table = workspace.resolve_input_file(tab_source, {".tab"})
        root, _ = workspace.context_identity()
    except workspace.WorkspaceError as exc:
        raise RunCompanionCopyError(str(exc)) from exc
    parts = _relative_parts(reference)
    text = genkey.read_text(encoding="utf-8", errors="replace")
    if not any(kind == "pvt" and raw == reference for kind, raw in companion_references(text)):
        raise RunCompanionCopyError("The case does not reference that table file.")
    case_dir = genkey.parent.resolve()
    destination = case_dir.joinpath(*parts)
    resolved = destination.resolve()
    if case_dir not in resolved.parents:
        raise RunCompanionCopyError("The copy would land outside the case folder.")
    if os.path.lexists(destination):
        raise RunCompanionCopyError(
            f"{destination.name} already exists in the case folder; nothing is ever overwritten."
        )
    try:
        data = table.read_bytes()
    except OSError as exc:
        raise RunCompanionCopyError(f"The chosen table could not be read: {exc}") from exc
    if not data:
        raise RunCompanionCopyError("The chosen table is empty.")
    sha256 = hashlib.sha256(data).hexdigest()
    approved_payload = {
        "source": str(genkey),
        "reference": reference,
        "tab_source": str(table),
        "sha256": sha256,
        "destination": str(destination),
    }
    return {
        "reference": reference,
        "tab_source": _display(table, root),
        "copy_to": _display(destination, root),
        "size": len(data),
        "sha256": sha256,
        "approved_payload": approved_payload,
    }


def preview(*, source: str, reference: str, tab_source: str) -> dict[str, Any]:
    """The exact copy the user is asked to approve (never includes the approval payload)."""
    planned = plan(source=source, reference=reference, tab_source=tab_source)
    return {key: value for key, value in planned.items() if key != "approved_payload"}


def _missing_dirs(destination: Path) -> list[Path]:
    missing: list[Path] = []
    folder = destination.parent
    while not folder.exists():
        missing.append(folder)
        folder = folder.parent
    return missing


def _remove_created(folders: list[Path]) -> None:
    for folder in folders:
        try:
            folder.rmdir()
        except OSError:
            break


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execute(args: dict[str, Any]) -> dict[str, Any]:
    """Copy exactly the approved table; the token must be minted for this exact request."""
    token = str(args.get("approval_token") or "")
    if not token:
        raise approvals.ApprovalError(
            "Copying a table into the case folder needs the user's approval; ask again and approve it."
        )
    generation = workspace.context_generation()
    planned = plan(
        source=str(args.get("source") or ""),
        reference=str(args.get("reference") or ""),
        tab_source=str(args.get("tab_source") or ""),
    )
    payload = planned["approved_payload"]
    approvals.consume(token, ACTION_KIND, payload, context_generation=generation)
    table = Path(payload["tab_source"])
    destination = Path(payload["destination"])
    try:
        data = table.read_bytes()
    except OSError as exc:
        raise RunCompanionCopyError(f"The chosen table could not be read: {exc}") from exc
    if hashlib.sha256(data).hexdigest() != payload["sha256"]:
        raise RunCompanionCopyError("The chosen table changed after the preview; nothing was copied.")
    created = _missing_dirs(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        _remove_created(created)
        raise RunCompanionCopyError(
            f"{destination.name} already exists in the case folder; nothing is ever overwritten."
        ) from exc
    except OSError as exc:
        destination.unlink(missing_ok=True)
        _remove_created(created)
        raise RunCompanionCopyError(f"The table could not be copied: {exc}") from exc
    if _file_sha256(destination) != payload["sha256"]:
        destination.unlink(missing_ok=True)
        _remove_created(created)
        raise RunCompanionCopyError("The copied table did not match the original; it was removed.")
    return {
        "ok": True,
        "reference": payload["reference"],
        "copy_to": planned["copy_to"],
        "size": planned["size"],
        "sha256": payload["sha256"],
        "next_step": "Preview the run again to confirm the case now finds this table.",
    }


def approve_and_execute(*, source: str, reference: str, tab_source: str, sha256: str, size: int) -> dict[str, Any]:
    """The user's explicit approval click: mint the single-use token for this exact copy and use it.

    sha256 and size are the values the user was shown in the preview; the copy is refused unless the
    table holds exactly those bytes now, so an approval can never cover a file the user did not review.
    """
    planned = plan(source=source, reference=reference, tab_source=tab_source)
    if not sha256 or planned["sha256"] != sha256.strip().lower() or planned["size"] != size:
        raise RunCompanionCopyError("The chosen table changed after the preview; nothing was copied.")
    token = approvals.mint(
        ACTION_KIND,
        planned["approved_payload"],
        context_generation=workspace.context_generation(),
    )["token"]
    return execute(
        {"source": source, "reference": reference, "tab_source": tab_source, "approval_token": token}
    )
