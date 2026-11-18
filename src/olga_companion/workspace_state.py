"""Workspace state-file locations and persistence helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from . import config

CASE_SUFFIXES = (".genkey", ".tab")
LIST_CAP = 500
WALK_CAP = 20000


def active_state_path() -> Path:
    """Return the active-case state path outside the selectable workspace."""
    return config.project_root() / "var" / "workspace-active.json"


def context_state_path() -> Path:
    """Return the durable workspace context path."""
    return config._workspace_context_path()


def read_active(
    state_path: Path,
    resolve_case: Callable[[str], Path],
    workspace_error: type[ValueError],
) -> dict[str, str | None]:
    """Read active state, returning an empty view for stale or malformed state."""
    if state_path.exists():
        try:
            path = json.loads(state_path.read_text(encoding="utf-8")).get("path")
            if path:
                resolved = resolve_case(path)
                return {"name": resolved.name, "path": str(resolved)}
        except (
            OSError,
            json.JSONDecodeError,
            workspace_error,
            config.WorkspaceContextError,
        ):
            return {"name": None, "path": None}
    return {"name": None, "path": None}


def write_active(state_path: Path, path: Path) -> dict[str, str | None]:
    """Persist and return the selected case."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"path": str(path)}), encoding="utf-8")
    return {"name": path.name, "path": str(path)}


def clear_active(state_path: Path) -> None:
    """Remove persisted active state when present."""
    if state_path.exists():
        state_path.unlink()
