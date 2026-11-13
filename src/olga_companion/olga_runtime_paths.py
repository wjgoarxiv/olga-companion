from __future__ import annotations

import os
from pathlib import Path


_PROGRAM_FILES_DIRS = ("Program Files", "Program Files (x86)")
_VENDORS = ("Schlumberger", "SLB")
_EXE_SUFFIXES = ("bin/opi.exe", "opi.exe", "OlgaExecutables/OLGA-*.exe")


def _windows_fixed_drives() -> list[str]:
    """Assigned C–Z fixed (non-network, non-removable) drives on Windows, else []."""
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return []
        get_type = windll.kernel32.GetDriveTypeW
        return [
            chr(ord("C") + i)
            for i in range(24)
            if get_type(f"{chr(ord('C') + i)}:\\") == 3
        ]
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — fall back to probes
        return []


def _existing_drive_letters() -> list[str]:
    """Assigned C–Z drive letters: fixed drives on Windows, mount check elsewhere."""
    fixed = _windows_fixed_drives()
    if fixed:
        return fixed
    try:
        import ctypes

        if getattr(ctypes, "windll", None) is not None:
            return []
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        pass
    return [
        chr(ord("C") + i)
        for i in range(24)
        if os.path.isdir(f"/mnt/{chr(ord('c') + i)}")
    ]


def _drive_roots() -> list[str]:
    """Filesystem roots to scan, C: always (it may hold the only install)."""
    roots = ["C:/", "/mnt/c"]
    for letter in _existing_drive_letters():
        if letter == "C":
            continue
        roots.append(f"{letter}:/")
        roots.append(f"/mnt/{letter.lower()}")
    return roots


def default_exe_globs() -> list[str]:
    """Install globs across existing drives, both path styles (fast-fail where absent)."""
    globs: list[str] = []
    for root in _drive_roots():
        base = root.rstrip("/")
        for program_dir in _PROGRAM_FILES_DIRS:
            for vendor in _VENDORS:
                for suffix in _EXE_SUFFIXES:
                    globs.append(f"{base}/{program_dir}/{vendor}/OLGA*/{suffix}")
    return globs


DEFAULT_OLGA_EXE_GLOBS = default_exe_globs() or [
    "/mnt/c/Program Files/Schlumberger/OLGA*/bin/opi.exe",
    "/mnt/c/Program Files/Schlumberger/OLGA*/opi.exe",
    "/mnt/c/Program Files (x86)/Schlumberger/OLGA*/bin/opi.exe",
    "/mnt/c/Program Files (x86)/Schlumberger/OLGA*/opi.exe",
    "/mnt/c/Program Files/SLB/OLGA*/bin/opi.exe",
    "/mnt/c/Program Files/SLB/OLGA*/opi.exe",
    "C:/Program Files/Schlumberger/OLGA*/opi.exe",
    "C:/Program Files/Schlumberger/OLGA*/bin/opi.exe",
    "C:/Program Files (x86)/Schlumberger/OLGA*/opi.exe",
    "C:/Program Files/SLB/OLGA*/opi.exe",
    "/mnt/c/Program Files/Schlumberger/OLGA*/OlgaExecutables/OLGA-*.exe",
    "/mnt/c/Program Files/SLB/OLGA*/OlgaExecutables/OLGA-*.exe",
    "C:/Program Files/Schlumberger/OLGA*/OlgaExecutables/OLGA-*.exe",
    "C:/Program Files/SLB/OLGA*/OlgaExecutables/OLGA-*.exe",
]


def executable_kind(exe: str) -> str:
    name = Path(exe).name.lower()
    if name.endswith(".py"):
        return "script"
    if name == "opi.exe":
        return "opi"
    if name.startswith("olga-") and name.endswith(".exe"):
        return "engine"
    return "executable"


def path_key(value: str) -> str:
    return os.path.normpath(value).replace("\\", "/").casefold()


def input_basename(value: str) -> str:
    return value.strip().replace("\\", "/").rsplit("/", 1)[-1]
