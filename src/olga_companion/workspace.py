"""The user's OLGA case workspace: contained case, result, and active state APIs."""

from __future__ import annotations

import json as json  # compatibility export
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from . import config
from . import workspace_active_context as _active_context
from . import workspace_paths as _paths
from . import workspace_root as _root
from . import workspace_state as _state
from .result_inventory import RESULT_SUFFIXES, scan_run_results, scan_workspace_results

CASE_SUFFIXES = _state.CASE_SUFFIXES
_LIST_CAP = _state.LIST_CAP
_WALK_CAP = _state.WALK_CAP
_CONTEXT_LOCK = threading.RLock()
_ACTIVE_SELECTION_SEQUENCE = 0
_BOUND_GENERATION: ContextVar[int | None] = ContextVar("olga_bound_generation", default=None)
_BOUND_SELECTIONS: ContextVar[int | None] = ContextVar("olga_bound_selections", default=None)


class WorkspaceError(ValueError):
    """A workspace path escaped the root, or a requested case does not exist."""


class StaleWorkspaceContextError(WorkspaceError):
    """A delayed request belongs to an older workspace generation."""


class StaleActiveSelectionError(StaleWorkspaceContextError):
    """A delayed active-case request was superseded by a newer user selection."""


@dataclass(frozen=True, slots=True)
class ActiveSelection:
    root: Path
    generation: int
    sequence: int


class ActiveCase(TypedDict):
    name: str | None
    path: str | None


def _active_state_path() -> Path:
    """Compatibility seam for the active-case state file."""
    return _state.active_state_path()


def _context_state_path() -> Path:
    """Compatibility alias for the durable workspace context file."""
    return _state.context_state_path()


def context_identity() -> tuple[Path, int]:
    """Return root and generation from one validated durable record read.

    Inside `bound_to` the generation must still be the bound one, so a long tool that
    resolves paths on its own (without holding the context lock) cannot silently start
    reading or writing the workspace the user switched to.
    """
    identity = config.workspace_context()
    bound = _BOUND_GENERATION.get()
    if bound is not None and identity[1] != bound:
        raise StaleWorkspaceContextError(
            "Workspace context changed; refresh the preview and approve again."
        )
    return identity


@contextmanager
def bound_to(generation: int, selections: int | None = None) -> Iterator[None]:
    """Make every context read in this call tree fail once the workspace generation moves.

    With `selections`, a tool in this call tree also may not record a case as active once
    the user has chosen one since: a late tool must not undo the user's newer selection.
    """
    generation_token = _BOUND_GENERATION.set(generation)
    selections_token = _BOUND_SELECTIONS.set(selections)
    try:
        yield
    finally:
        _BOUND_SELECTIONS.reset(selections_token)
        _BOUND_GENERATION.reset(generation_token)


def context_generation() -> int:
    return context_identity()[1]


@contextmanager
def expected_context(generation: int) -> Iterator[tuple[Path, int]]:
    """Hold the workspace context stable after checking an expected generation."""
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 0
    ):
        raise StaleWorkspaceContextError("Workspace context generation is invalid.")
    with _CONTEXT_LOCK:
        identity = context_identity()
        if identity[1] != generation:
            raise StaleWorkspaceContextError(
                "Workspace context changed; refresh the preview and approve again."
            )
        yield identity


def contained(rel_or_path: str) -> Path:
    """Resolve a path and require it to stay inside the workspace root."""
    with _CONTEXT_LOCK:
        root, _ = context_identity()
        return _contained_at(root, rel_or_path)


def resolve_input_file(identifier: str, suffixes: set[str] | tuple[str, ...]) -> Path:
    """Resolve a user/model input under the workspace or application sandbox."""
    if not identifier or not identifier.strip():
        raise WorkspaceError("a file identifier is required")
    allowed_suffixes = {suffix.casefold() for suffix in suffixes}
    if not allowed_suffixes:
        raise WorkspaceError("at least one file suffix is required")
    with _CONTEXT_LOCK:
        workspace_root, _ = context_identity()
        return _paths.resolve_input_file_at(
            identifier,
            allowed_suffixes,
            workspace_root,
            config.sandbox_root(),
            WorkspaceError,
        )


def _contained_at(root: Path, rel_or_path: str) -> Path:
    return _paths.contained_at(root, rel_or_path, WorkspaceError)


def _list_files_at(root: Path, suffixes: tuple[str, ...]) -> list[dict]:
    return _paths.list_files_at(
        root,
        suffixes,
        list_cap=_LIST_CAP,
        walk_cap=_WALK_CAP,
    )


def _list_files(suffixes: tuple[str, ...]) -> list[dict]:
    """Compatibility wrapper using one locked workspace-root snapshot."""
    with _CONTEXT_LOCK:
        root, _ = context_identity()
        return _list_files_at(root, suffixes)


def list_cases() -> list[dict]:
    """Every ``.genkey``/``.tab`` case file under the workspace root."""
    with _CONTEXT_LOCK:
        root, _ = context_identity()
        return _list_files_at(root, CASE_SUFFIXES)


def list_results() -> list[dict]:
    """Every workspace and run-sandbox result with an opaque id."""
    with _CONTEXT_LOCK:
        root, _ = context_identity()
        return _list_results_at(root)


def _list_results_at(root: Path) -> list[dict]:
    return _paths.list_results_at(
        root,
        config.sandbox_root() / "runs",
        list_cap=_LIST_CAP,
        walk_cap=_WALK_CAP,
        scan_workspace=scan_workspace_results,
        scan_runs=scan_run_results,
    )


def resolve_result(identifier: str) -> Path:
    """Resolve a server-issued result id or a contained legacy path."""
    with _CONTEXT_LOCK:
        # The resolver reads the workspace root itself; check the bound generation and keep
        # the root from changing while it does.
        context_identity()
        return _paths.resolve_result(identifier, RESULT_SUFFIXES, WorkspaceError)


def _raw_active_path(state_path: Path) -> str | None:
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    path = payload.get("path") if isinstance(payload, dict) else None
    return path if isinstance(path, str) and path else None


def _foreign_active_path(path: str) -> bool:
    """True when a stored path is outside the workspace or inside the sandbox."""
    root, _ = context_identity()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    sandbox = config.sandbox_root().resolve()
    if resolved == sandbox or sandbox in resolved.parents:
        return True
    root_resolved = root.resolve()
    return resolved != root_resolved and root_resolved not in resolved.parents


def active() -> ActiveCase:
    """Return the shared active case, or an empty view for stale state.

    A sandbox or other out-of-workspace path left in the state file is dropped.
    The case file itself is left untouched.
    """
    with _CONTEXT_LOCK:
        state_path = _active_state_path()
        raw = _raw_active_path(state_path)
        if raw and _foreign_active_path(raw):
            _state.clear_active(state_path)
            return {"name": None, "path": None}
        return _state.read_active(
            state_path,
            lambda path: resolve_input_file(path, CASE_SUFFIXES),
            WorkspaceError,
        )


def active_path() -> str | None:
    return active().get("path")


def active_workspace_rel() -> str | None:
    """Workspace-relative path of the active case, with forward slashes."""
    with _CONTEXT_LOCK:
        root, _generation = context_identity()
        current = active()
        path = current.get("path")
        if not path:
            return None
        try:
            relative = Path(path).resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return None
        return relative.as_posix()


def active_workspace() -> ActiveCase:
    """Return the frontend view, excluding external agent-only cases."""
    with _CONTEXT_LOCK:
        root, _ = context_identity()
        return _active_workspace_at(root)


def _active_workspace_at(root: Path) -> ActiveCase:
    return _active_context.contained_active(
        root,
        active(),
        _contained_at,
        CASE_SUFFIXES,
        WorkspaceError,
    )


def _write_active(path: Path) -> ActiveCase:
    return _state.write_active(_active_state_path(), path)


def active_selection_sequence() -> int:
    """Counts the user's case selections; an agent tool touching a case does not advance it."""
    with _CONTEXT_LOCK:
        return _ACTIVE_SELECTION_SEQUENCE


def active_path_if_selection_unchanged(selections: int) -> tuple[bool, str | None]:
    """Read the active case only if the user has not chosen one since `selections`.

    The comparison and the read share the context lock, so a click cannot land between them.
    """
    with _CONTEXT_LOCK:
        if _ACTIVE_SELECTION_SEQUENCE != selections:
            return False, None
        try:
            return True, active_path()
        except WorkspaceError:
            return True, None


def begin_active_selection(generation: int) -> ActiveSelection:
    """Register user intent before request work so completion order cannot win."""
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 0
    ):
        raise StaleWorkspaceContextError("Workspace context generation is invalid.")
    global _ACTIVE_SELECTION_SEQUENCE
    with _CONTEXT_LOCK:
        root, current_generation = context_identity()
        if generation != current_generation:
            raise StaleWorkspaceContextError(
                "Workspace context changed; refresh the case list and select again."
            )
        _ACTIVE_SELECTION_SEQUENCE += 1
        return ActiveSelection(
            root=root, generation=generation, sequence=_ACTIVE_SELECTION_SEQUENCE
        )


def set_active_rel(rel: str, *, selection: ActiveSelection | None = None) -> ActiveCase:
    """Record a workspace-contained case selected by the client."""
    global _ACTIVE_SELECTION_SEQUENCE
    if selection is not None:
        candidate = _contained_at(selection.root, rel)
        with _CONTEXT_LOCK:
            if context_identity() != (selection.root, selection.generation):
                raise StaleWorkspaceContextError(
                    "Workspace context changed; refresh the case list and select again."
                )
            if selection.sequence != _ACTIVE_SELECTION_SEQUENCE:
                raise StaleActiveSelectionError(
                    "A newer case selection replaced this delayed request."
                )
            if not candidate.is_file() or candidate.suffix.lower() not in CASE_SUFFIXES:
                raise WorkspaceError(f"not a workspace case: {rel!r}")
            return _write_active(candidate)
    with _CONTEXT_LOCK:
        path = contained(rel)
        if not path.is_file() or path.suffix.lower() not in CASE_SUFFIXES:
            raise WorkspaceError(f"not a workspace case: {rel!r}")
        _ACTIVE_SELECTION_SEQUENCE += 1  # a selection without a registered intent is still the user's
        return _write_active(path)


SANDBOX_ACTIVE_NOTICE = "샌드박스 복사본은 검토용이며 저장은 case_publish 승인으로"


def _active_case_path(root: Path, path: str) -> Path:
    """Resolve one workspace case. A sandbox or outside path is never active."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise WorkspaceError(f"not a workspace case: {path!r}") from exc
    sandbox = config.sandbox_root().resolve()
    if resolved == sandbox or sandbox in resolved.parents:
        raise WorkspaceError(SANDBOX_ACTIVE_NOTICE)
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        raise WorkspaceError("input file must stay inside the workspace or app sandbox")
    if resolved.name.startswith("-"):
        raise WorkspaceError("input file names must not start with '-'")
    if not resolved.is_file() or resolved.suffix.lower() not in CASE_SUFFIXES:
        raise WorkspaceError(f"not a workspace case: {path!r}")
    return resolved


def set_active_path(path: str) -> ActiveCase:
    """Record a workspace case touched by an agent. Sandbox copies stay inactive."""
    with _CONTEXT_LOCK:
        bound = _BOUND_SELECTIONS.get()
        if bound is not None and bound != _ACTIVE_SELECTION_SEQUENCE:
            raise StaleActiveSelectionError(
                "A newer case selection replaced this tool's case."
            )
        root, _ = context_identity()
        return _write_active(_active_case_path(root, path))


def clear_active() -> None:
    global _ACTIVE_SELECTION_SEQUENCE
    with _CONTEXT_LOCK:
        _ACTIVE_SELECTION_SEQUENCE += 1
        _state.clear_active(_active_state_path())


def context_snapshot() -> dict[str, Any]:
    with _CONTEXT_LOCK:
        root, generation = context_identity()
        return {
            "root": str(root),
            "cases": _list_files_at(root, CASE_SUFFIXES),
            "active": _active_workspace_at(root),
            "generation": generation,
        }


def results_snapshot() -> dict[str, Any]:
    with _CONTEXT_LOCK:
        root, generation = context_identity()
        return {
            "root": str(root),
            "results": _list_results_at(root),
            "generation": generation,
        }


def _switch_root_locked(path: str | Path) -> dict[str, Any]:
    target, generation, changed = _root.plan_root_transition(
        path,
        context_identity=context_identity,
        env_workspace_root=os.environ.get("OLGA_WORKSPACE_DIR"),
        workspace_error=WorkspaceError,
    )
    if not changed:
        return {**context_snapshot(), "changed": False, "revoked": 0}

    from .agent import approvals

    with approvals.revoke_all_barrier() as revoked:
        clear_active()
        config.commit_workspace_context(target, generation)
    return {
        **context_snapshot(),
        "changed": True,
        "generation": generation,
        "revoked": revoked,
    }


def switch_root(path: str | Path) -> dict[str, Any]:
    """Safely change root and invalidate all state bound to the old context."""
    with _CONTEXT_LOCK:
        return _switch_root_locked(path)


def open_case_path(path: str | Path) -> dict[str, Any]:
    """Switch to a selected case's parent and activate it atomically."""
    selected = _root.selected_case_path(path, CASE_SUFFIXES, WorkspaceError)
    with _CONTEXT_LOCK:
        context = _switch_root_locked(selected.parent)
        activated = set_active_rel(selected.name)
        return {
            **context_snapshot(),
            "changed": context["changed"],
            "revoked": context["revoked"],
            "active": activated,
        }
