"""Cross-platform privacy hardening for app-owned OAuth state."""

from __future__ import annotations

import csv
import os
import re
import subprocess
from pathlib import Path, PureWindowsPath


_WINDOWS_COMMAND_TIMEOUT = 10
_SID_PATTERN = re.compile(r"S-\d+(?:-\d+)+")


def harden_private_path(
    path: Path,
    *,
    directory: bool,
    platform: str | None = None,
) -> None:
    """Remove inherited Windows ACEs or apply owner-only POSIX modes."""
    platform = os.name if platform is None else platform
    if platform != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    sid = _windows_current_sid()
    permission = f"*{sid}:(OI)(CI)F" if directory else f"*{sid}:F"
    result = _run_windows(
        [
            _windows_executable("icacls.exe"),
            str(path),
            "/inheritance:r",
            "/grant:r",
            permission,
        ]
    )
    if result.returncode != 0:
        raise OSError("Windows credential-store ACL hardening failed")


def _windows_current_sid() -> str:
    result = _run_windows(
        [_windows_executable("whoami.exe"), "/user", "/fo", "csv", "/nh"]
    )
    if result.returncode != 0:
        raise OSError("Windows credential-store owner lookup failed")
    try:
        row = next(csv.reader(result.stdout.splitlines()))
        sid = row[1].strip()
    except (IndexError, StopIteration, csv.Error):
        raise OSError("Windows credential-store owner lookup failed") from None
    if _SID_PATTERN.fullmatch(sid) is None:
        raise OSError("Windows credential-store owner lookup failed")
    return sid


def _windows_executable(name: str) -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(PureWindowsPath(system_root, "System32", name))


def _run_windows(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=_WINDOWS_COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise OSError("Windows credential-store privacy command failed") from None
