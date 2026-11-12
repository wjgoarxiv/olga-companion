from __future__ import annotations

from pathlib import Path


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
