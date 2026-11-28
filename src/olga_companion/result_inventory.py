from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from .run_identity import approved_changes_by_hash
from .run_records import RunRecordError, load_run_record

RESULT_SUFFIXES = (".tpl", ".ppl")
MIN_RESULT_BYTES = 16  # smaller files cannot contain the OLGA result header


# On POSIX st_ctime is the inode change time, which a copy that restores mtime cannot forge.
# On Windows it is the creation time, so no stat field proves the bytes are unchanged and a
# cached digest is only trusted for a short, explicit window.
_CTIME_IS_CHANGE_TIME = os.name != "nt"
_UNPROVEN_REUSE_SECONDS = 30.0
_clock = time.monotonic
_HASH_CACHE: dict[tuple[str, int, int, int, int], tuple[str, float]] = {}
_HASH_CACHE_LIMIT = 1024


def _current_sha256(path: str, stat: os.stat_result) -> str | None:
    """Digest of the file as it is now, reusing a cached one only while that is safe."""
    key = (path, stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_ctime_ns)
    now = _clock()
    cached = _HASH_CACHE.get(key)
    if cached is not None:
        digest, stamped = cached
        proven = _CTIME_IS_CHANGE_TIME and stat.st_ctime_ns != stat.st_mtime_ns
        if proven or now - stamped < _UNPROVEN_REUSE_SECONDS:
            return digest
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    if len(_HASH_CACHE) >= _HASH_CACHE_LIMIT:
        _HASH_CACHE.clear()
    _HASH_CACHE[key] = (hasher.hexdigest(), now)
    return hasher.hexdigest()


_META_CACHE: dict[tuple[str, int, int], dict] = {}


def case_meta_for_case(case: Path) -> dict:
    """The title and display names a case file carries; empty for an older case."""
    from .case_spec_recovery import read_case_meta

    try:
        stat = case.stat()
    except OSError:
        return {}
    key = (str(case), stat.st_size, stat.st_mtime_ns)
    if key not in _META_CACHE:
        if len(_META_CACHE) >= _HASH_CACHE_LIMIT:
            _META_CACHE.clear()
        _META_CACHE[key] = dict(read_case_meta(case))
    return _META_CACHE[key]


def case_meta_beside(result: Path, preferred_name: str | None = None) -> dict:
    """Meta of the case a result file sits next to: the named one, else the only .genkey there."""
    try:
        cases = sorted(entry for entry in result.parent.iterdir() if entry.suffix.lower() == ".genkey" and entry.is_file())
    except OSError:
        return {}
    chosen = next((entry for entry in cases if entry.name == preferred_name), None)
    if chosen is None:
        chosen = next((entry for entry in cases if entry.stem == result.stem), cases[0] if len(cases) == 1 else None)
    return case_meta_for_case(chosen) if chosen is not None else {}


def run_result_id(run_id: str, name: str) -> str:
    return f"run:{run_id}/{name}"


def _result_item(entry: os.DirEntry[str], rel: str, origin: str) -> dict | None:
    if not entry.is_file(follow_symlinks=False):
        return None
    suffix = Path(entry.name).suffix.lower()
    if suffix not in RESULT_SUFFIXES:
        return None
    stat = entry.stat(follow_symlinks=False)
    if stat.st_size < MIN_RESULT_BYTES:
        return None
    normalized = rel.replace(chr(92), "/")
    identifier = f"{origin}:{normalized}"
    return {
        "name": entry.name,
        "rel": normalized,
        "size": stat.st_size,
        "suffix": suffix,
        "modified_ns": stat.st_mtime_ns,
        "id": identifier,
        "result_id": identifier,
        "origin": origin,
    }


def _run_provenance(run_dir: Path) -> tuple[str, dict, dict | None]:
    try:
        record = load_run_record(run_dir)
    except FileNotFoundError:
        return "unknown", {"kind": "legacy_run_directory", "receipt": "missing"}, None
    except RunRecordError as exc:
        return "unknown", {"kind": "invalid_run_receipt", "receipt_error": str(exc)}, None
    source = record["source"]
    runtime = record["runtime"]
    return str(record["state"]), {
        "kind": "run_receipt",
        "schema_version": record["schema_version"],
        "source_name": source.get("name"),
        "source_sha256": source.get("sha256"),
        "runtime_candidate_id": runtime.get("candidate_id"),
        "runtime_version": runtime.get("version"),
        "selection_id": record.get("selection_id"),
    }, record


def _newest(items: list[dict], list_cap: int) -> list[dict]:
    return sorted(items, key=lambda item: (-item["modified_ns"], item["id"].lower()))[:list_cap]


def _count(counts: dict | None, found: int, walk_capped: bool) -> None:
    """Add to the caller's tally: results seen before the cut, and whether the walk stopped early."""
    if counts is not None:
        counts["found"] = counts.get("found", 0) + found
        counts["walk_capped"] = counts.get("walk_capped", False) or walk_capped


def scan_workspace_results(root: Path, *, list_cap: int, walk_cap: int, counts: dict | None = None) -> list[dict]:
    """The newest ``list_cap`` results in the workspace root and its immediate child directories.

    Every entry up to ``walk_cap`` is looked at, so the cut keeps the newest results rather
    than whichever came first in directory order.
    """
    if not root.is_dir():
        _count(counts, 0, False)
        return []
    out: list[dict] = []
    inspected = 0
    capped = False
    with os.scandir(root) as entries:
        for entry in entries:
            inspected += 1
            if inspected > walk_cap:
                capped = True
                break
            if entry.is_file(follow_symlinks=False):
                item = _result_item(entry, entry.name, "workspace")
                if item:
                    out.append(item)
            elif entry.is_dir(follow_symlinks=False):
                with os.scandir(entry.path) as children:
                    for child in children:
                        inspected += 1
                        if inspected > walk_cap:
                            capped = True
                            break
                        item = _result_item(child, f"{entry.name}/{child.name}", "workspace")
                        if item:
                            out.append(item)
                        elif child.is_dir(follow_symlinks=False) and child.name.casefold() == "results":
                            with os.scandir(child.path) as grandchildren:
                                for grandchild in grandchildren:
                                    inspected += 1
                                    if inspected > walk_cap:
                                        capped = True
                                        break
                                    nested = _result_item(
                                        grandchild,
                                        f"{entry.name}/{child.name}/{grandchild.name}",
                                        "workspace",
                                    )
                                    if nested:
                                        out.append(nested)
    _count(counts, len(out), capped)
    return _newest(out, list_cap)


def _edit_source(source: dict) -> dict[str, str]:
    """The workspace case a run can be edited from: only while it holds the exact bytes the run
    recorded. Otherwise the reason the result offers no edit."""
    from . import workspace

    path_value, recorded = source.get("resolved_path"), source.get("sha256")
    if not isinstance(path_value, str) or not isinstance(recorded, str):
        return {"reason": "unrecorded"}
    try:
        root = workspace.context_identity()[0].resolve()
        path = Path(path_value).resolve()
    except (OSError, RuntimeError, ValueError, workspace.WorkspaceError):
        return {"reason": "outside_workspace"}
    if not path.is_relative_to(root) or path.suffix.casefold() != ".genkey":
        return {"reason": "outside_workspace"}
    try:
        stat = path.stat()
    except OSError:
        return {"reason": "missing"}
    if _current_sha256(str(path), stat) != recorded:
        return {"reason": "changed"}
    return {"rel": path.relative_to(root).as_posix()}


def _genkey_name_counts() -> dict[str, int]:
    """How many workspace .genkey files carry each file name. The workspace makes a case active by
    its name, so a name two cases share cannot be opened from a result without guessing."""
    from . import workspace

    counts: dict[str, int] = {}
    try:
        cases = workspace.list_cases()
    except (OSError, workspace.WorkspaceError):
        return counts
    for case in cases:
        name = str(case.get("name", ""))
        if name.casefold().endswith(".genkey"):
            counts[name.casefold()] = counts.get(name.casefold(), 0) + 1
    return counts


def scan_run_results(runs_root: Path, *, list_cap: int, walk_cap: int, counts: dict | None = None) -> list[dict]:
    """The newest ``list_cap`` result files directly inside each run directory, never nested debug artifacts.

    The walk only stats files; receipts are read and outputs hashed for the results kept.
    """
    if not runs_root.is_dir():
        _count(counts, 0, False)
        return []
    found: list[tuple[dict, os.DirEntry[str], os.DirEntry[str]]] = []
    inspected = 0
    capped = False
    with os.scandir(runs_root) as run_entries:
        for run_entry in run_entries:
            inspected += 1
            if inspected > walk_cap:
                capped = True
                break
            if not run_entry.is_dir(follow_symlinks=False):
                continue
            with os.scandir(run_entry.path) as file_entries:
                for file_entry in file_entries:
                    inspected += 1
                    if inspected > walk_cap:
                        capped = True
                        break
                    item = _result_item(file_entry, f"{run_entry.name}/{file_entry.name}", "run")
                    if item:
                        found.append((item, run_entry, file_entry))
    _count(counts, len(found), capped)
    kept = {id(item) for item in _newest([item for item, _run, _file in found], list_cap)}
    runs: dict[str, dict] = {}
    shared: dict[str, dict | None] = {"approved": None, "case_names": None}
    out: list[dict] = []
    for item, run_entry, file_entry in found:
        if id(item) not in kept:
            continue
        run = runs.get(run_entry.name)
        if run is None:
            run_state, provenance, record = _run_provenance(Path(run_entry.path))
            run = runs[run_entry.name] = {
                "state": run_state, "provenance": provenance, "record": record, "meta": None, "edit_source": None,
            }
        _describe_run_item(item, run_entry.name, file_entry, run, shared)
        out.append(item)
    return _newest(out, list_cap)


def _describe_run_item(
    item: dict, run_name: str, file_entry: os.DirEntry[str], run: dict, shared: dict[str, dict | None]
) -> None:
    """Add the run's receipt, lineage and edit source to one listed result."""
    record = run["record"]
    provenance = run["provenance"]
    source = record["source"] if record is not None else {}
    runtime = record["runtime"] if record is not None else {}
    output = next(
        (
            candidate
            for candidate in (record.get("outputs", []) if record is not None else [])
            if isinstance(candidate, dict)
            and (
                candidate.get("result_id") == item["result_id"]
                or candidate.get("name") == item["name"]
            )
        ),
        None,
    )
    recorded_ok = record.get("ok") if record is not None else None
    item_provenance = provenance
    lineage_status = None
    if output is not None:
        # Membership alone proves nothing: the bytes must still be the
        # ones the run recorded, or the file was replaced afterwards.
        recorded = output.get("sha256")
        recorded_size = output.get("size")
        # A different size is already proof of change; skip hashing it.
        current = (
            None
            if isinstance(recorded_size, int) and recorded_size != item["size"]
            else _current_sha256(file_entry.path, file_entry.stat(follow_symlinks=False))
        )
        lineage_status = (
            "receipt_output"
            if isinstance(recorded, str) and current == recorded
            else "receipt_changed"
        )
    elif record is not None:
        item_provenance = {
            **provenance,
            "kind": "unlisted_run_file",
            "receipt": "output_not_listed",
        }
    item.update(
        {
            "run_id": run_name,
            "root": record.get("workspace_root") if record is not None else None,
            "run_state": run["state"],
            "run_ok": recorded_ok if isinstance(recorded_ok, bool) else None,
            "runtime_kind": runtime.get("kind"),
            "output_sha256": output.get("sha256") if output is not None else None,
            "source_name": source.get("name"),
            "source_path": source.get("resolved_path"),
            "candidate_id": runtime.get("candidate_id"),
            "runtime_version": runtime.get("version"),
            "provenance": item_provenance,
            "lineage_status": lineage_status,
        }
    )
    if run["meta"] is None:
        run["meta"] = case_meta_beside(Path(file_entry.path), source.get("name"))
    if run["meta"]:
        item["case_meta"] = run["meta"]
    if run["edit_source"] is None:
        edit_source = _edit_source(source)
        if "rel" in edit_source:
            if shared["case_names"] is None:
                shared["case_names"] = _genkey_name_counts()
            if shared["case_names"].get(edit_source["rel"].rsplit("/", 1)[-1].casefold(), 0) > 1:
                edit_source = {"reason": "same_name"}
        run["edit_source"] = edit_source
    item["edit_source"] = run["edit_source"]
    source_sha = source.get("sha256")
    if isinstance(source_sha, str):
        if shared["approved"] is None:
            shared["approved"] = approved_changes_by_hash()
        if source_sha in shared["approved"]:
            item["approved_change"] = shared["approved"][source_sha]
