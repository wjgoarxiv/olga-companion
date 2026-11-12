from __future__ import annotations

import heapq
import json
import os
import re
import stat
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
MAX_HISTORY_LIMIT = 100
MAX_HISTORY_INSPECT = 10_000
MAX_HISTORY_PARSE = 200
MAX_RUN_RECORD_BYTES = 1024 * 1024
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_REQUIRED_FIELDS = {
    "schema_version",
    "run_id",
    "phase",
    "state",
    "source",
    "companions",
    "runtime",
    "selection_id",
    "validation",
    "timestamps",
    "command",
    "exit_code",
    "failure",
    "outputs",
}


class RunRecordError(ValueError):
    """A persisted run receipt exists but cannot be trusted."""


def require_run_id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise RunRecordError(f"Invalid run id: {run_id!r}")
    return run_id


def _validate(record: Any, *, expected_run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise RunRecordError("Run receipt is corrupt: expected a JSON object.")
    schema = record.get("schema_version")
    if schema != SCHEMA_VERSION:
        raise RunRecordError(f"Unknown run receipt schema: {schema!r}.")
    missing = sorted(_REQUIRED_FIELDS - record.keys())
    if missing:
        raise RunRecordError("Run receipt is corrupt: missing " + ", ".join(missing) + ".")
    run_id = record.get("run_id")
    if not isinstance(run_id, str):
        raise RunRecordError("Run receipt is corrupt: run_id must be a string.")
    require_run_id(run_id)
    if expected_run_id is not None and run_id != expected_run_id:
        raise RunRecordError("Run receipt is corrupt: directory and receipt run ids differ.")
    phase = record.get("phase")
    state = record.get("state")
    if phase not in {"prepared", "running", "terminal"}:
        raise RunRecordError("Run receipt is corrupt: invalid phase.")
    allowed_states = {
        "prepared": {"prepared"},
        "running": {"running"},
        "terminal": {"completed", "failed", "cancelled", "timed_out"},
    }
    if state not in allowed_states[phase]:
        raise RunRecordError("Run receipt is corrupt: state does not match its phase.")
    source = record.get("source")
    if not isinstance(source, dict) or not {"name", "sha256", "staged_sha256"} <= source.keys():
        raise RunRecordError("Run receipt is corrupt: source provenance is incomplete.")
    runtime = record.get("runtime")
    runtime_fields = {"candidate_id", "runtime_id", "version", "kind", "exe"}
    if not isinstance(runtime, dict) or not runtime_fields <= runtime.keys():
        raise RunRecordError("Run receipt is corrupt: runtime provenance is incomplete.")
    timestamps = record.get("timestamps")
    timestamp_fields = {"prepared_at", "started_at", "finished_at"}
    if not isinstance(timestamps, dict) or not timestamp_fields <= timestamps.keys():
        raise RunRecordError("Run receipt is corrupt: lifecycle timestamps are incomplete.")
    if not isinstance(record.get("companions"), list):
        raise RunRecordError("Run receipt is corrupt: companions must be a list.")
    if not isinstance(record.get("validation"), dict):
        raise RunRecordError("Run receipt is corrupt: validation must be an object.")
    if not isinstance(record.get("selection_id"), str) or not record["selection_id"]:
        raise RunRecordError("Run receipt is corrupt: selection_id is missing.")
    if not isinstance(record.get("command"), list) or not all(isinstance(part, str) for part in record["command"]):
        raise RunRecordError("Run receipt is corrupt: command must be an argv list.")
    if not isinstance(record.get("outputs"), list):
        raise RunRecordError("Run receipt is corrupt: outputs must be a list.")
    root = record.get("workspace_root")
    if root is not None and not isinstance(root, str):
        raise RunRecordError("Run receipt is corrupt: workspace_root must be a string.")
    return record


def write_run_record(run_dir: Path, record: Mapping[str, Any]) -> None:
    validated = _validate(dict(record), expected_run_id=run_dir.name)
    target = run_dir / "run.json"
    temporary = run_dir / f".run.json.{uuid.uuid4().hex}.tmp"
    payload = json.dumps(validated, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def load_run_record(run_dir: Path) -> dict[str, Any]:
    target = run_dir / "run.json"
    try:
        target_stat = target.stat(follow_symlinks=False)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise RunRecordError(f"Run receipt could not be read: {exc}") from exc
    if not stat.S_ISREG(target_stat.st_mode):
        raise RunRecordError("Run receipt is unsafe: run.json must be a regular file, not a symlink.")
    if target_stat.st_size > MAX_RUN_RECORD_BYTES:
        raise RunRecordError(f"Run receipt is too large (maximum {MAX_RUN_RECORD_BYTES} bytes).")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened_stat.st_mode):
                raise RunRecordError("Run receipt is unsafe: run.json must be a regular file.")
            data = handle.read(MAX_RUN_RECORD_BYTES + 1)
    except FileNotFoundError:
        raise
    except RunRecordError:
        raise
    except OSError as exc:
        raise RunRecordError(f"Run receipt could not be opened safely: {exc}") from exc
    if len(data) > MAX_RUN_RECORD_BYTES:
        raise RunRecordError(f"Run receipt is too large (maximum {MAX_RUN_RECORD_BYTES} bytes).")
    try:
        record = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RunRecordError("Run receipt is corrupt: run.json is not UTF-8.") from exc
    except json.JSONDecodeError as exc:
        raise RunRecordError(f"Run receipt is corrupt JSON: {exc.msg}.") from exc
    return _validate(record, expected_run_id=run_dir.name)


def _history_timestamp_ns(record: Mapping[str, Any], fallback_ns: int) -> int:
    timestamps = record.get("timestamps")
    prepared_at = timestamps.get("prepared_at") if isinstance(timestamps, Mapping) else None
    if not isinstance(prepared_at, str) or not prepared_at:
        return fallback_ns
    try:
        parsed = datetime.fromisoformat(prepared_at.replace("Z", "+00:00"))
    except ValueError:
        return fallback_ns
    if parsed.tzinfo is None:
        return fallback_ns
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1_000


def recent_run_records(runs_root: Path, *, limit: int, source_path: str | None = None) -> list[dict[str, Any]]:
    bounded_limit = min(max(int(limit), 1), MAX_HISTORY_LIMIT)
    if not runs_root.is_dir():
        return []
    candidates: list[tuple[int, str, str]] = []
    inspected = 0
    with os.scandir(runs_root) as entries:
        for entry in entries:
            inspected += 1
            if inspected > MAX_HISTORY_INSPECT:
                break
            if not entry.is_dir(follow_symlinks=False):
                continue
            run_dir = Path(entry.path)
            receipt_path = run_dir / "run.json"
            try:
                receipt_stat = receipt_path.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(receipt_stat.st_mode):
                continue
            candidate = (receipt_stat.st_mtime_ns, entry.name, str(run_dir))
            if len(candidates) < MAX_HISTORY_PARSE:
                heapq.heappush(candidates, candidate)
            elif candidate > candidates[0]:
                heapq.heapreplace(candidates, candidate)

    found: list[tuple[int, int, str, dict[str, Any]]] = []
    for receipt_mtime_ns, run_id, run_dir_value in candidates:
        run_dir = Path(run_dir_value)
        try:
            record = load_run_record(run_dir)
        except FileNotFoundError:
            continue
        except RunRecordError as exc:
            if source_path is not None:
                continue
            record = {
                "run_id": run_id,
                "phase": "invalid",
                "state": "receipt_error",
                "receipt_error": str(exc),
            }
        if source_path is not None and record["source"].get("resolved_path") != source_path:
            continue
        record["_run_dir"] = str(run_dir)
        found.append(
            (
                _history_timestamp_ns(record, receipt_mtime_ns),
                receipt_mtime_ns,
                run_id,
                record,
            )
        )
    found.sort(key=lambda item: item[:3], reverse=True)
    return [record for _, _, _, record in found[:bounded_limit]]
