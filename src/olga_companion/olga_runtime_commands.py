from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from .olga_runtime_paths import executable_kind, path_key


def build_command(
    exe: str,
    case_name: str,
    *,
    wsl_init_path: Path,
    wsl_interop_path: Path,
    platform: str | None = None,
    threads: int = 12,
) -> list[str]:
    kind = executable_kind(exe)
    if kind == "script":
        return [sys.executable, exe, case_name]
    if kind == "engine":
        # Native OLGA is launched by the Explorer broker with the GUI-proven,
        # case-only argv. Keep this logical command free of bridge/shell args.
        return [exe, case_name]
    if kind == "opi":
        arguments = ["-f", case_name]
    else:
        arguments = [case_name]

    exe_path = Path(exe)
    parts = exe_path.parts
    current_platform = sys.platform if platform is None else platform
    is_wsl_windows_exe = (
        current_platform.startswith("linux")
        and exe_path.suffix.lower() == ".exe"
        and len(parts) >= 4
        and parts[1] == "mnt"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    )
    if (
        is_wsl_windows_exe
        and wsl_init_path.is_file()
        and not wsl_interop_path.is_file()
    ):
        return [str(wsl_init_path), exe, exe, *arguments]
    return [exe, *arguments]


def build_display_command(command: Sequence[str], exe: str) -> list[str]:
    """Return path-free argv suitable for displaying to a user."""
    matches = [
        index for index, part in enumerate(command) if path_key(part) == path_key(exe)
    ]
    kind = executable_kind(exe)
    if kind == "script":
        script_index = matches[-1] if matches else 1
        values = [Path(command[0]).name, Path(exe).name, *command[script_index + 1 :]]
    else:
        runtime_index = matches[-1] if matches else 0
        values = [Path(exe).name, *command[runtime_index + 1 :]]
    return [
        Path(value).name
        if Path(value).is_absolute()
        else value.replace("\\", "/").rsplit("/", 1)[-1]
        for value in values
    ]
