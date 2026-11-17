"""Contained presentation of the active workspace case."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def contained_active(
    root: Path,
    current: dict[str, str | None],
    contain: Callable[[Path, str], Path],
    case_suffixes: tuple[str, ...],
    workspace_error: type[ValueError],
) -> dict[str, str | None]:
    """Hide active agent cases that do not belong to the current workspace."""
    path = current.get("path")
    if not path:
        return {"name": None, "path": None}
    try:
        contained_path = contain(root, path)
    except workspace_error:
        return {"name": None, "path": None}
    if (
        not contained_path.is_file()
        or contained_path.suffix.lower() not in case_suffixes
    ):
        return {"name": None, "path": None}
    return {"name": contained_path.name, "path": str(contained_path)}
