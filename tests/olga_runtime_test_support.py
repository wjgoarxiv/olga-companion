from __future__ import annotations

import os
from pathlib import Path


def windows_temp_dir() -> Path | None:
    """The Windows user's temp folder as seen from WSL, found at run time rather than named in the repo."""
    configured = os.environ.get("OLGA_WINDOWS_TEMP")
    if configured:
        return Path(configured)
    users = Path("/mnt/c/Users")
    if not users.is_dir():
        return None
    # Other accounts' folders (Default, Public, ...) are not writable or not in use; take the busiest writable one.
    found = [path for path in users.glob("*/AppData/Local/Temp") if path.is_dir() and os.access(path, os.W_OK)]
    return max(found, key=lambda path: path.stat().st_mtime) if found else None


def _installed_release(
    root: Path, version: str, *, opi: bool = True, engine: bool = True
) -> list[str]:
    install = root / f"OLGA {version}"
    paths: list[str] = []
    if opi:
        path = install / "opi.exe"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub")
        paths.append(str(path))
    if engine:
        path = install / "OlgaExecutables" / f"OLGA-{version}.exe"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub")
        paths.append(str(path))
    return paths


def _qualified_case(root: Path, version: str) -> Path:
    simulation = root / "simulation"
    results = simulation / "results"
    results.mkdir(parents=True)
    case = simulation / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n")
    (results / "case.out").write_text(
        f"VERSION : OLGA {version}.35696\n"
        "INPUT FILE : case.genkey\n"
        "**************** NORMAL STOP IN EXECUTION ****************\n"
    )
    return case
