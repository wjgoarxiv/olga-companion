"""Workspace-contained input, case inventory, and result path operations."""

from __future__ import annotations

from pathlib import Path

from . import config


def contained_at(
    root: Path, rel_or_path: str, workspace_error: type[ValueError]
) -> Path:
    """Resolve a path and require it to remain under ``root``."""
    path = Path(rel_or_path).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if path != root and root not in path.parents:
        raise workspace_error(f"path escapes the workspace root: {rel_or_path!r}")
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
    roots = (workspace_root.resolve(), sandbox_root.resolve())
    # The results inventory names files "run:<id>/<name>" and "workspace:<name>";
    # such an id stays inside its own root.
    for prefix, base in (("run:", roots[1] / "runs"), ("workspace:", roots[0])):
        if identifier.startswith(prefix):
            base = base.resolve()
            resolved = (base / identifier.removeprefix(prefix)).resolve()
            if base not in resolved.parents:
                raise workspace_error("input file must stay inside the workspace or app sandbox")
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
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise workspace_error(
            "input file must stay inside the workspace or app sandbox"
        )
    if resolved.name.startswith("-"):
        raise workspace_error("input file names must not start with '-'")
    if resolved.suffix.casefold() not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise workspace_error(f"input file must use one of these extensions: {allowed}")
    if not resolved.is_file():
        raise workspace_error(f"input file not found: {identifier!r}")
    return resolved


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
                raise workspace_error(
                    "result path must stay inside the workspace or run sandbox"
                )
            root = next(
                root for root in allowed if resolved == root or root in resolved.parents
            )
        else:
            root = config.workspace_root().resolve()
            candidate = root / value
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise workspace_error(
            "result path must stay inside the workspace or run sandbox"
        )
    if not resolved.is_file() or resolved.suffix.lower() not in result_suffixes:
        raise workspace_error(f"result file not found: {identifier!r}")
    if resolved.stat().st_size == 0:
        # A failed run leaves a 0-byte .ppl/.tpl behind. Handing it to the parser
        # produces a bare UnboundLocalError from pyfas, which reads like a broken
        # install rather than a broken run.
        raise workspace_error(
            f"result file is empty: {resolved.name} (0 bytes). "
            "The run that should have written it did not finish."
        )
    return resolved
