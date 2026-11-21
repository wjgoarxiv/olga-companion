"""A record written next to each .tab the app makes, and the fresh / stale / unknown check.

The record names the .mfl (a plain file name in the same folder), its SHA-256, the table's
SHA-256 and the grid. A table without a valid record is "unknown", never "fresh" or "stale".
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePath
from typing import Any

from .genkey_static import file_sha256

SCHEMA = 1
SUFFIX = ".made-from.json"


def record_path(tab: Path) -> Path:
    return tab.with_name(tab.name + SUFFIX)


def write_record(
    tab: Path,
    *,
    mfl: Path,
    mfl_sha256: str,
    grid: dict[str, list[float]],
    grid_source: str,
) -> Path:
    """Write the record beside the table through a temporary file; a left-over record
    whose table was gone is replaced, because it described nothing."""
    target = record_path(tab)
    record = {
        "schema": SCHEMA,
        "tab": tab.name,
        "tab_sha256": file_sha256(tab),
        "mfl": mfl.name,
        "mfl_sha256": mfl_sha256,
        "grid": {"temperatures_k": list(grid["temperatures_k"]), "pressures_pa": list(grid["pressures_pa"])},
        "grid_source": grid_source,
    }
    partial = tab.with_name(f".{os.urandom(6).hex()}.making{SUFFIX}")
    try:
        partial.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _state(state: str, reason: str, mfl: str | None) -> dict[str, Any]:
    return {"state": state, "reason": reason, "mfl": mfl}


def _read_record(tab: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(record_path(tab).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return None
    name = record.get("mfl")
    if not isinstance(name, str) or not name or PurePath(name).name != name or "\\" in name:
        return None
    if not all(isinstance(record.get(key), str) for key in ("mfl_sha256", "tab_sha256")):
        return None
    if not isinstance(record.get("grid"), dict):
        return None
    return record


def fluid_freshness(tab: Path) -> dict[str, Any]:
    """fresh: the .mfl and the table match the record; stale: the .mfl changed after the
    table was made; unknown: no usable record, or it no longer describes this table."""
    if not record_path(tab).exists():
        return _state("unknown", "no_record", None)
    record = _read_record(tab)
    if record is None:
        return _state("unknown", "bad_record", None)
    name = record["mfl"]
    if file_sha256(tab) != record["tab_sha256"]:
        return _state("unknown", "table_changed", name)
    mfl = tab.with_name(name)
    if not mfl.is_file():
        return _state("unknown", "mfl_missing", name)
    if file_sha256(mfl) != record["mfl_sha256"]:
        return _state("stale", "mfl_changed", name)
    return _state("fresh", "matches", name)


def preview_freshness(companions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Freshness of each found PVT table the run preview lists."""
    rows = []
    for entry in companions:
        if entry.get("kind") != "pvt" or not entry.get("found") or not entry.get("resolved_path"):
            continue
        rows.append({"reference": entry["reference"], **fluid_freshness(Path(entry["resolved_path"]))})
    return rows
