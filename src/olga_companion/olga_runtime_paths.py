from __future__ import annotations

import os
from pathlib import Path


DEFAULT_OLGA_EXE_GLOBS = [
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
