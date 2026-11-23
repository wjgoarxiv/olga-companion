"""Workspace-contained input, case inventory, and result path operations."""

from __future__ import annotations

from pathlib import Path

from . import config
from .path_safety import is_network_path


def _refuse_network(value: str, workspace_error: type[ValueError]) -> None:
    if is_network_path(value):
        raise _coded(
            workspace_error, "path_outside_workspace",
            "network paths are not used; keep files inside the workspace",
        )


def _coded(workspace_error: type[ValueError], error_code: str, message: str) -> ValueError:
    """The workspace error with a stable machine code; the message text is unchanged."""
    error = workspace_error(message)
    error.error_code = error_code  # type: ignore[attr-defined]
    return error


def contained_at(
    root: Path, rel_or_path: str, workspace_error: type[ValueError]
) -> Path:
    """Resolve a path and require it to remain under ``root``."""
    _refuse_network(rel_or_path, workspace_error)
    path = Path(rel_or_path).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if path != root and root not in path.parents:
        raise _coded(
            workspace_error, "path_outside_workspace",
            f"path escapes the workspace root: {rel_or_path!r}",
        )
    return path


_NAME_LOOKUP_WALK_CAP = 20000


def _locate_by_name(
    root: Path, name: str, workspace_error: type[ValueError]
) -> Path | None:
    """Find a uniquely named file anywhere under ``root``.

    The case inventory is listed recursively, so the UI can surface — and make
    active — a case that lives in a subfolder. Tools are then handed the
    displayed file name, which on its own would only resolve at the workspace
    root. Ambiguity is reported rather than guessed.
    """
    matches: list[Path] = []
    inspected = 0
    for path in root.rglob("*"):
        inspected += 1
        if inspected > _NAME_LOOKUP_WALK_CAP:
            break
        if path.name != name or not path.is_file():
            continue
        matches.append(path)
        if len(matches) > 1:
            break
    if not matches:
        return None
    if len(matches) > 1:
        raise workspace_error(
            f"{name!r} matches more than one file in the workspace; "
            "pass the path relative to the workspace root"
        )
    return matches[0]


def resolve_input_file_at(
    identifier: str,
    allowed_suffixes: set[str],
    workspace_root: Path,
    sandbox_root: Path,
    workspace_error: type[ValueError],
) -> Path:
    """Resolve an input inside either the workspace or application sandbox."""
    _refuse_network(identifier, workspace_error)
    roots =(workspace_root.resolve(), sandbox_root.resolve())
    # The results inventory names files "run:<id>/<name>" and "workspace:<name>";
    # such an id stays inside its own root.
    for prefix, base in (("run:", roots[1] / "runs"), ("workspace:", roots[0])):
        if identifier.startswith(prefix):
            base = base.resolve()
            resolved = (base / identifier.removeprefix(prefix)).resolve()
            if base not in resolved.parents:
                raise _coded(
                    workspace_error, "path_outside_workspace",
                    "input file must stay inside the workspace or app sandbox",
                )
            identifier = str(resolved)
            break
    candidate = Path(identifier).expanduser()
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    # A bare file name that is not at the workspace root may still name a case
    # the inventory listed from a subfolder. Every check below still applies to
    # whatever this locates.
    if not resolved.is_file() and identifier == Path(identifier).name:
        located = _locate_by_name(roots[0], identifier, workspace_error)
        if located is not None:
            resolved = located
    elif (
        not resolved.is_file()
        and not Path(identifier).expanduser().is_absolute()
        and ".." not in Path(identifier).parts
    ):
        # A relative path with a wrong folder: the root's own folder name in front, or a
        # folder that does not exist. Still one file of that name, or nothing.
        located = _guessed_folder(roots[0], Path(identifier), workspace_error)
        if located is not None:
            resolved = located
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise _coded(
            workspace_error, "path_outside_workspace",
            "input file must stay inside the workspace or app sandbox",
        )
    if resolved.name.startswith("-"):
        raise workspace_error("input file names must not start with '-'")
    if resolved.suffix.casefold() not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise workspace_error(f"input file must use one of these extensions: {allowed}")
    if not resolved.is_file():
        raise _coded(
            workspace_error, "path_not_found",
            f"input file not found: {identifier!r}{_same_type_hint(roots[0], allowed_suffixes)}",
        )
    return resolved


_HINT_FILES = 8


def _guessed_folder(root: Path, rel: Path, workspace_error: type[ValueError]) -> Path | None:
    parts = rel.parts
    for k in range(len(parts) - 1, 0, -1):
        if parts[:k] == root.parts[-k:] and (root.joinpath(*parts[k:])).is_file():
            return root.joinpath(*parts[k:]).resolve()
    return _locate_by_name(root, parts[-1], workspace_error)


def _same_type_hint(root: Path, suffixes: set[str]) -> str:
    found = list_files_at(root, tuple(suffixes), list_cap=_HINT_FILES + 1, walk_cap=_NAME_LOOKUP_WALK_CAP)
    if not found:
        return ""
    names = ", ".join(Path(item["rel"]).as_posix()[:120] for item in found[:_HINT_FILES])
    more = ", …" if len(found) > _HINT_FILES else ""
    return f". Workspace files of this type: {names}{more}"


def list_files_at(
    root: Path,
    suffixes: tuple[str, ...],
    *,
    list_cap: int,
    walk_cap: int,
) -> list[dict]:
    """List contained files while bounding traversal and response sizes."""
    root_resolved = root.resolve()
    files: list[dict] = []
    inspected = 0
    for path in root.rglob("*"):
        inspected += 1
        if inspected > walk_cap or len(files) >= list_cap:
            break
        if not (path.is_file() and path.suffix.lower() in suffixes):
            continue
        try:
            rel = str(path.resolve().relative_to(root_resolved))
        except ValueError:
            continue
        files.append(
            {
                "name": path.name,
                "rel": rel,
                "size": path.stat().st_size,
                "suffix": path.suffix.lower(),
            }
        )
    files.sort(key=lambda item: item["rel"].lower())
    return files


def list_results_at(
    root: Path,
    runs_root: Path,
    *,
    list_cap: int,
    walk_cap: int,
    scan_workspace,
    scan_runs,
) -> list[dict]:
    """List workspace and run-sandbox results by opaque result identifier."""
    workspace_results = scan_workspace(root, list_cap=list_cap, walk_cap=walk_cap)
    run_results = scan_runs(runs_root, list_cap=list_cap, walk_cap=walk_cap)
    return sorted(
        [*workspace_results, *run_results],
        key=lambda item: (-item["modified_ns"], item["id"].lower()),
    )[:list_cap]


def resolve_result(
    identifier: str,
    result_suffixes: tuple[str, ...],
    workspace_error: type[ValueError],
) -> Path:
    """Resolve a server-issued result id or a contained legacy path."""
    if not identifier or not identifier.strip():
        raise workspace_error("a result identifier is required")
    _refuse_network(identifier, workspace_error)
    if identifier.startswith("workspace:"):
        root = config.workspace_root().resolve()
        candidate = root / identifier.removeprefix("workspace:")
    elif identifier.startswith("run:"):
        root = (config.sandbox_root() / "runs").resolve()
        candidate = root / identifier.removeprefix("run:")
    else:
        value = Path(identifier).expanduser()
        if value.is_absolute():
            candidate = value
            allowed = [
                config.workspace_root().resolve(),
                (config.sandbox_root() / "runs").resolve(),
            ]
            resolved = candidate.resolve()
            if not any(
                resolved == root or root in resolved.parents for root in allowed
            ):
                raise _coded(
                    workspace_error, "path_outside_workspace",
                    "result path must stay inside the workspace or run sandbox",
                )
            root = next(
                root for root in allowed if resolved == root or root in resolved.parents
            )
        else:
            root = config.workspace_root().resolve()
            candidate = root / value
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise _coded(
            workspace_error, "path_outside_workspace",
            "result path must stay inside the workspace or run sandbox",
        )
    if not resolved.is_file() or resolved.suffix.lower() not in result_suffixes:
        raise _coded(workspace_error, "path_not_found", f"result file not found: {identifier!r}")
    if resolved.stat().st_size == 0:
        # A failed run leaves a 0-byte .ppl/.tpl behind. Handing it to the parser
        # produces a bare UnboundLocalError from pyfas, which reads like a broken
        # install rather than a broken run.
        raise workspace_error(
            f"result file is empty: {resolved.name} (0 bytes). "
            "The run that should have written it did not finish."
        )
    return resolved
