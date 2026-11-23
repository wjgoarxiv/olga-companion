"""Delete a workspace case file after the user's approval: the file goes to the Windows Recycle Bin,
never away for good. Run results recorded from the case stay where they are.

This module is not an agent tool; only the UI's approval route calls ``delete``.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from . import config, workspace
from .agent import approvals
from .run_records import MAX_HISTORY_LIMIT, recent_run_records

ACTION_KIND = "case_delete"


class CaseDeleteError(ValueError):
    """The case cannot be deleted; nothing was moved."""


class StaleCaseError(CaseDeleteError):
    """The case file changed after the user reviewed it; nothing was moved."""


def _runs_root() -> Path:
    return config.sandbox_root() / "runs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _case_path(root: Path, rel: str) -> Path:
    """A regular .genkey file inside the workspace, named by its workspace-relative path."""
    if (Path(root) / rel).is_symlink():
        raise CaseDeleteError("Only a case file itself can be deleted, not a link to one.")
    path = workspace._contained_at(root, rel)
    if path.suffix.casefold() != ".genkey" or path.is_symlink() or not path.is_file():
        raise CaseDeleteError("Only an existing .genkey case in this workspace can be deleted.")
    return path


def _linked_results(path: Path) -> int:
    return len(recent_run_records(_runs_root(), limit=MAX_HISTORY_LIMIT, source_path=str(path)))


def review(rel: str) -> dict[str, Any]:
    """What the approval card shows. Reads only."""
    root, _ = workspace.context_identity()
    path = _case_path(root, rel)
    return {
        "rel": path.relative_to(Path(root).resolve()).as_posix(),
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "linked_results": _linked_results(path),
    }


def delete(rel: str, sha256: str, context_generation: int) -> dict[str, Any]:
    """The user's Approve click: move exactly the reviewed bytes to the Recycle Bin."""
    payload = {"rel": rel, "sha256": sha256}
    token = approvals.mint(ACTION_KIND, payload, context_generation=context_generation)["token"]
    with workspace.expected_context(context_generation) as (root, generation):
        approvals.consume(token, ACTION_KIND, payload, context_generation=generation)
        path = _case_path(root, rel)
        if _sha256(path) != sha256:
            raise StaleCaseError("The case file changed after the review; nothing was deleted.")
        was_active = workspace.active_path() is not None and Path(workspace.active_path()).resolve() == path
        recycle(path)
        if was_active:
            workspace.clear_active()
    return {"state": "recycled", "rel": rel, "closed": was_active}


_DRIVE_FIXED = 3
_BITBUCKET = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket"
_POLICY = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"


def bin_refusal(
    *,
    drive_type: int,
    volume_found: bool,
    no_recycle_policy: bool,
    nuke_on_delete: int | None,
    max_capacity_mb: int | None,
    size: int,
) -> str | None:
    """Why Windows might delete this file for good instead of recycling it, or None when it will recycle.

    ``None`` settings mean the volume was never configured, so the Windows default (Recycle Bin on) applies.
    """
    if drive_type != _DRIVE_FIXED:
        return "Only a case on a local fixed drive can go to the Recycle Bin; nothing was deleted."
    if not volume_found:
        return "The Recycle Bin settings for this drive could not be read; nothing was deleted."
    if no_recycle_policy or nuke_on_delete == 1:
        return "The Recycle Bin is turned off for this drive; nothing was deleted."
    if max_capacity_mb is not None and size > max_capacity_mb * 1024 * 1024:
        return "The file is larger than this drive's Recycle Bin allows; nothing was deleted."
    return None


def _on_windows() -> bool:
    return os.name == "nt"


def _reg_dword(hive: Any, key: str, name: str) -> int | None:
    import winreg

    try:
        with winreg.OpenKey(hive, key) as handle:
            value, kind = winreg.QueryValueEx(handle, name)
    except OSError:
        return None
    return int(value) if kind == winreg.REG_DWORD else None


def _recycle_refusal(path: Path) -> str | None:
    """Read the drive type, the Recycle Bin policy and this volume's Recycle Bin settings, then judge."""
    import ctypes
    import winreg

    root = str(path.resolve())[:3]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buffer = ctypes.create_unicode_buffer(64)
    found = bool(kernel32.GetVolumeNameForVolumeMountPointW(root, buffer, 64))
    start, end = buffer.value.find("{"), buffer.value.find("}")
    guid = buffer.value[start : end + 1] if found and 0 <= start < end else ""
    volume = rf"{_BITBUCKET}\Volume\{guid}"
    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    return bin_refusal(
        drive_type=kernel32.GetDriveTypeW(root),
        volume_found=bool(guid),
        no_recycle_policy=any(_reg_dword(h, _POLICY, "NoRecycleFiles") == 1 for h in hives),
        nuke_on_delete=_reg_dword(winreg.HKEY_CURRENT_USER, volume, "NukeOnDelete")
        or _reg_dword(winreg.HKEY_CURRENT_USER, _BITBUCKET, "NukeOnDelete"),
        max_capacity_mb=_reg_dword(winreg.HKEY_CURRENT_USER, volume, "MaxCapacity"),
        size=path.stat().st_size,
    )


def recycle(path: Path) -> None:
    """Send one file to the Windows Recycle Bin, or refuse. Never deletes permanently.

    Windows silently deletes for good when a drive's Recycle Bin is off, so that is checked first and refused.
    """
    if not _on_windows():
        raise CaseDeleteError("The Recycle Bin is only available on Windows; nothing was deleted.")
    refusal = _recycle_refusal(path)
    if refusal:
        raise CaseDeleteError(refusal)
    import ctypes
    from ctypes import wintypes

    class _ShFileOp(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    class _BinInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]

    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    target = str(path.resolve())
    info = _BinInfo(ctypes.sizeof(_BinInfo), 0, 0)
    if shell32.SHQueryRecycleBinW(target[:3], ctypes.byref(info)) != 0:
        raise CaseDeleteError("This drive has no Recycle Bin; nothing was deleted.")
    fo_delete = 0x0003
    flags = 0x0040 | 0x0010 | 0x0004 | 0x0400 | 0x4000  # ALLOWUNDO, NOCONFIRMATION, SILENT, NOERRORUI, WANTNUKEWARNING
    operation = _ShFileOp(None, fo_delete, target + "\0", None, flags, False, None, None)
    result = shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted:
        raise CaseDeleteError("The Recycle Bin refused the file; nothing was deleted.")
    if path.exists():
        raise CaseDeleteError("The file is still in the workspace; nothing was deleted.")
