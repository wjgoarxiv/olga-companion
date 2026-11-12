from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

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


def scan_workspace_results(root: Path, *, list_cap: int, walk_cap: int) -> list[dict]:
    """Scan only the workspace root and its immediate child directories."""
    if not root.is_dir():
        return []
    out: list[dict] = []
    inspected = 0
    with os.scandir(root) as entries:
        for entry in entries:
            inspected += 1
            if inspected > walk_cap or len(out) >= list_cap:
                break
            if entry.is_file(follow_symlinks=False):
                item = _result_item(entry, entry.name, "workspace")
                if item:
                    out.append(item)
            elif entry.is_dir(follow_symlinks=False):
                with os.scandir(entry.path) as children:
                    for child in children:
                        inspected += 1
                        if inspected > walk_cap or len(out) >= list_cap:
                            break
                        item = _result_item(child, f"{entry.name}/{child.name}", "workspace")
                        if item:
                            out.append(item)
                        elif child.is_dir(follow_symlinks=False) and child.name.casefold() == "results":
                            with os.scandir(child.path) as grandchildren:
                                for grandchild in grandchildren:
                                    inspected += 1
                                    if inspected > walk_cap or len(out) >= list_cap:
                                        break
                                    nested = _result_item(
                                        grandchild,
                                        f"{entry.name}/{child.name}/{grandchild.name}",
                                        "workspace",
                                    )
                                    if nested:
                                        out.append(nested)
    return out


def scan_run_results(runs_root: Path, *, list_cap: int, walk_cap: int) -> list[dict]:
    """Scan direct files inside each run directory, never nested debug artifacts."""
    if not runs_root.is_dir():
        return []
    out: list[dict] = []
    inspected = 0
    with os.scandir(runs_root) as run_entries:
        for run_entry in run_entries:
            inspected += 1
            if inspected > walk_cap or len(out) >= list_cap:
                break
            if not run_entry.is_dir(follow_symlinks=False):
                continue
            run_state, provenance, record = _run_provenance(Path(run_entry.path))
            with os.scandir(run_entry.path) as file_entries:
                for file_entry in file_entries:
                    inspected += 1
                    if inspected > walk_cap or len(out) >= list_cap:
                        break
                    item = _result_item(file_entry, f"{run_entry.name}/{file_entry.name}", "run")
                    if item:
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
                                "run_id": run_entry.name,
                                "root": record.get("workspace_root") if record is not None else None,
                                "run_state": run_state,
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
                        out.append(item)
    return out
