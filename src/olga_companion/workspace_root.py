"""Workspace-root transition planning and selected-case validation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def plan_root_transition(
    path: str | Path,
    *,
    context_identity: Callable[[], tuple[Path, int]],
    env_workspace_root: str | None,
    workspace_error: type[ValueError],
) -> tuple[Path, int, bool]:
    """Validate and describe a root transition before its atomic transaction."""
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise workspace_error(f"not a directory: {path}")
    current, generation = context_identity()
    if target == current:
        return target, generation, False
    if env_workspace_root:
        raise workspace_error(
            "OLGA_WORKSPACE_DIR fixes the workspace root for this process"
        )
    return target, generation + 1, True


def selected_case_path(
    path: str | Path,
    case_suffixes: tuple[str, ...],
    workspace_error: type[ValueError],
) -> Path:
    """Resolve and validate a native-dialog case selection."""
    selected = Path(path).expanduser().resolve()
    if not selected.is_file() or selected.suffix.lower() not in case_suffixes:
        raise workspace_error("selected file must be an existing .genkey or .tab case")
    return selected
