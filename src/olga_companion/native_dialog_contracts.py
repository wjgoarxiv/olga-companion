"""Boundary validation and path translation for native Windows dialogs."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

DialogKind = Literal["folder", "case-open", "exe-pick", "save-as"]

MAX_PATH_CHARS = 4096
MAX_SUGGESTED_CHARS = 255
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DRIVE_PATH_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$", re.DOTALL)
_WSL_DRIVE_RE = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$", re.DOTALL)
_RESERVED_DEVICE_RE = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$",
    re.IGNORECASE,
)


class NativeDialogError(ValueError):
    """Invalid dialog input or unsupported/unsafe path representation."""


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def require_request_id(request_id: str) -> str:
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise NativeDialogError("request_id must be a 1-64 character ASCII token")
    return request_id


def require_bounded(value: str | None, *, name: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit or _has_control(value):
        raise NativeDialogError(f"{name} is invalid or exceeds {limit} characters")
    return value


def _validate_windows_components(remainder: str) -> list[str]:
    components = [
        component
        for component in remainder.replace("/", "\\").split("\\")
        if component
    ]
    for component in components:
        if component in (".", ".."):
            raise NativeDialogError("dot path components are not supported")
        if ":" in component:
            raise NativeDialogError("NTFS alternate data stream paths are not supported")
        if component.endswith((".", " ")):
            raise NativeDialogError(
                "Windows path components may not end in a dot or space"
            )
        device_stem = component.split(".", 1)[0]
        if _RESERVED_DEVICE_RE.fullmatch(device_stem):
            raise NativeDialogError("Windows reserved device names are not supported")
    return components


def windows_to_local(value: str, *, native_windows: bool | None = None) -> Path:
    """Convert a safe absolute drive path to this process's local path form."""
    native_windows = os.name == "nt" if native_windows is None else native_windows
    value = require_bounded(value, name="selected path", limit=MAX_PATH_CHARS)
    normalized = value.replace("/", "\\")
    if normalized.startswith("\\"):
        raise NativeDialogError("UNC and Windows device paths are not supported")
    match = _DRIVE_PATH_RE.fullmatch(normalized)
    if match is None:
        raise NativeDialogError(
            "the native dialog returned a relative or unsupported path"
        )
    drive, remainder = match.groups()
    parts = _validate_windows_components(remainder)
    if native_windows:
        tail = "\\".join(parts)
        return Path(
            f"{drive.upper()}:\\{tail}" if tail else f"{drive.upper()}:\\"
        )
    return Path("/mnt") / drive.lower() / Path(*parts)


def local_to_windows(
    value: Path | str,
    *,
    native_windows: bool | None = None,
) -> str:
    """Convert a local absolute drive mount to a Windows drive path without wslpath."""
    native_windows = os.name == "nt" if native_windows is None else native_windows
    raw = str(value)
    require_bounded(raw, name="initial path", limit=MAX_PATH_CHARS)
    if native_windows:
        normalized = raw.replace("/", "\\")
        match = (
            None
            if normalized.startswith("\\")
            else _DRIVE_PATH_RE.fullmatch(normalized)
        )
        if match is None:
            raise NativeDialogError("only absolute Windows drive paths are supported")
        drive, remainder = match.groups()
        parts = _validate_windows_components(remainder)
        tail = "\\".join(parts)
        return f"{drive.upper()}:\\{tail}" if tail else f"{drive.upper()}:\\"
    normalized = raw.replace("\\", "/")
    match = _WSL_DRIVE_RE.fullmatch(normalized)
    if match is None:
        raise NativeDialogError(
            "only Windows drive paths mounted under /mnt/<drive> are supported in WSL"
        )
    drive, remainder = match.groups()
    parts = _validate_windows_components(remainder or "")
    tail = "\\".join(parts)
    return f"{drive.upper()}:\\{tail}" if tail else f"{drive.upper()}:\\"
