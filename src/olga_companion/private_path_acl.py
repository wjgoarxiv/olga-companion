"""Verified private permissions across POSIX, native Windows, and WSL DrvFS."""

from __future__ import annotations

import errno
import logging
import os
import re
import stat
import subprocess
from pathlib import Path

from .runtime_logging import LOGGER_NAME


_WINDOWS_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = [Environment]::GetEnvironmentVariable('OLGA_PRIVATE_PATH')
$isDirectory = [Environment]::GetEnvironmentVariable('OLGA_PRIVATE_KIND') -eq 'directory'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
$administrators = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
$allowed = New-Object 'System.Collections.Generic.List[string]'
foreach ($candidate in @($user.Value, $system.Value, $administrators.Value)) {
    if (-not $allowed.Contains($candidate)) { [void]$allowed.Add($candidate) }
}
if ($isDirectory) {
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
} else {
    $security = New-Object System.Security.AccessControl.FileSecurity
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::None
}
$security.SetOwner($user)
$security.SetAccessRuleProtection($true, $false)
foreach ($sid in @($user, $system, $administrators)) {
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    [void]$security.AddAccessRule($rule)
}
(Get-Item -LiteralPath $target -Force).SetAccessControl($security)
$actual = Get-Acl -LiteralPath $target
if (-not $actual.AreAccessRulesProtected) { exit 20 }
$seen = New-Object 'System.Collections.Generic.HashSet[string]'
$rules = $actual.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
foreach ($rule in $rules) {
    if ($rule.IsInherited) { exit 21 }
    if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) { exit 22 }
    $sid = $rule.IdentityReference.Value
    if ($allowed -notcontains $sid) { exit 23 }
    $required = [System.Security.AccessControl.FileSystemRights]::FullControl
    if (($rule.FileSystemRights -band $required) -ne $required) { exit 24 }
    [void]$seen.Add($sid)
}
if ($seen.Count -ne $allowed.Count) { exit 25 }
"""


def _windows_path(path: Path) -> str | None:
    if os.name == "nt":
        return str(path)
    parts = path.absolute().parts
    if (
        len(parts) >= 4
        and parts[1] == "mnt"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    ):
        drive = parts[2].upper()
        tail = "\\".join(parts[3:])
        return f"{drive}:\\{tail}"
    return None


def _powershell_executable() -> Path:
    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        executable = (
            system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
    else:
        executable = Path(
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        )
    if not executable.is_file():
        raise OSError(errno.EACCES, "Windows ACL enforcement is unavailable.")
    return executable


_DETAIL_LIMIT = 300
_SID_PATTERN = re.compile(r"S-\d+-\d+(?:-\d+)+")
_USER_DIR = re.compile(r"(?i)(?:^|[\\/])Users[\\/]([^\\/\r\n]+?)(?=[\\/])")
# A non-final segment may contain spaces (Program Files). The separator is one
# slash, so a later UNC path (\\server\share) is not swallowed into the match.
_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\)(?:[^\\/\r\n]+[\\/](?![\\/]))*(?:[^\\/\s\r\n]+)?"
)


def _redacted_tail(raw: bytes | None, windows_path: str) -> str:
    """Last few hundred characters of PowerShell stderr with identities removed."""
    if not raw:
        return ""
    text = raw[-4096:].decode("utf-8", errors="replace")
    # A WSL process often has no USERNAME. The name still sits in Users\<name>,
    # including names that contain spaces, so redact that segment wherever it repeats.
    secrets = [
        (windows_path, "<path>"),
        (str(Path.home()), "<path>"),
        (os.environ.get("USERNAME", ""), "<user>"),
        (os.environ.get("USER", ""), "<user>"),
        *[(name, "<user>") for name in _USER_DIR.findall(text)],
    ]
    for secret, placeholder in secrets:
        if len(secret) >= 3:
            text = re.sub(re.escape(secret), placeholder, text, flags=re.IGNORECASE)
    text = _SID_PATTERN.sub("<sid>", text)
    text = _PATH_PATTERN.sub("<path>", text)
    return " ".join(text.split())[-_DETAIL_LIMIT:]


def _log_acl_failure(kind: str, code: object, detail: str) -> None:
    logging.getLogger(LOGGER_NAME).warning(
        "private_acl_failed kind=%s code=%s detail=%s", kind, code, detail
    )


def _apply_windows_acl(windows_path: str, *, directory: bool) -> None:
    kind = "directory" if directory else "file"
    environment = os.environ.copy()
    environment["OLGA_PRIVATE_PATH"] = windows_path
    environment["OLGA_PRIVATE_KIND"] = kind
    if os.name != "nt":
        entries = [entry for entry in environment.get("WSLENV", "").split(":") if entry]
        exported = {entry.partition("/")[0] for entry in entries}
        entries.extend(
            name
            for name in ("OLGA_PRIVATE_PATH", "OLGA_PRIVATE_KIND")
            if name not in exported
        )
        environment["WSLENV"] = ":".join(entries)
    try:
        result = subprocess.run(
            [
                str(_powershell_executable()),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _WINDOWS_ACL_SCRIPT,
            ],
            check=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        timed_out = isinstance(exc, subprocess.TimeoutExpired)
        _log_acl_failure(
            kind,
            "timeout" if timed_out else "oserror",
            _redacted_tail(type(exc).__name__.encode() + b" " + str(exc).encode(), windows_path),
        )
        raise OSError(errno.EACCES, "Windows ACL enforcement failed.") from exc
    if result.returncode != 0:
        _log_acl_failure(kind, result.returncode, _redacted_tail(result.stderr, windows_path))
        raise OSError(
            errno.EACCES,
            f"Windows ACL verification failed (code {result.returncode}).",
        )


def harden_private_path(path: Path, *, directory: bool) -> None:
    """Apply and verify an owner-private path policy, or fail closed."""
    if path.is_symlink():
        raise OSError(errno.ELOOP, "Private storage cannot be a symbolic link.")
    metadata = path.stat(follow_symlinks=False)
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(metadata.st_mode):
        raise OSError(errno.EINVAL, "Private storage has the wrong file type.")
    windows_path = _windows_path(path)
    if windows_path is not None:
        _apply_windows_acl(windows_path, directory=directory)
        return
    expected_mode = 0o700 if directory else 0o600
    os.chmod(path, expected_mode)
    actual_mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    if actual_mode != expected_mode:
        raise OSError(errno.EACCES, "Private storage mode verification failed.")
