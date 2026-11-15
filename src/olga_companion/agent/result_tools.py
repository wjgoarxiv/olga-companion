from __future__ import annotations

import math
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import results, workspace
from ..result_provenance import ensure_result_source_unchanged
from .tool_validation import DEFAULT_PATH_BINDINGS as DEFAULT_PATHS
from .tool_validation import PathBindings, ToolError

MAX_TRANSCRIPT_ROWS: Final = 200
MAX_LISTED_TIMESTEPS: Final = 20


class _InventoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: int = Field(default=0, strict=True, ge=0)
    limit: int = Field(default=20, strict=True, ge=1, le=100)


class _TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: float = Field(ge=0)
    end: float = Field(ge=0)


class _SeriesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result_id: str = Field(min_length=1, max_length=4096)
    variable: str = Field(min_length=1, max_length=128)
    position: str | None = Field(default=None, min_length=1, max_length=512)
    value_unit: str | None = Field(default=None, min_length=1, max_length=64)
    time_unit: str | None = Field(default=None, min_length=1, max_length=64)
    quantity_kind: Literal["point", "delta"] = "point"
    time_range: _TimeRange | None = None
    offset: int = Field(default=0, strict=True, ge=0)
    row_limit: int = Field(default=5, strict=True, ge=1, le=5000)
    truncation: Literal["head", "tail", "uniform"] = "head"


def _stable_hash(path: Path) -> str:
    before = results.file_sha256(path)
    return ensure_result_source_unchanged(path, before, results.file_sha256)


def canonical_result_id(value: str) -> str:
    prefix, separator, relative = value.partition(":")
    raw_parts = relative.split("/")
    parts = PurePosixPath(relative).parts
    if (
        not separator
        or prefix not in {"workspace", "run"}
        or not relative
        or relative.startswith(("/", "\\"))
        or "\\" in relative
        or ":" in relative
        or any(not part for part in raw_parts)
        or any(part in {".", ".."} for part in parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in relative)
    ):
        raise ToolError("Use the opaque result_id returned by results_inventory.")
    return value


def load(args: dict[str, Any], paths: PathBindings = DEFAULT_PATHS) -> dict[str, Any]:
    """Load result metadata without exposing its resolved filesystem path."""
    result_id = canonical_result_id(str(args["path"]))
    output = results.load_result(paths.result_file(result_id))
    allowed = {
        "ok", "file_type", "variables", "branches", "timesteps", "time_range",
        "cached", "source_mutated", "source_sha256_after",
    }
    public = {key: value for key, value in output.items() if key in allowed}
    return {"result_id": result_id, **public}


def inventory(args: dict[str, Any], paths: PathBindings = DEFAULT_PATHS) -> dict[str, Any]:
    """Return a bounded, newest-first, path-private result inventory."""
    try:
        request = _InventoryRequest.model_validate(args)
    except ValidationError as exc:
        raise ToolError("Invalid result inventory pagination.") from exc
    snapshot = workspace.results_snapshot()
    entries = sorted(
        snapshot.get("results", []),
        key=lambda item: (-int(item.get("modified_ns", 0)), str(item.get("id", "")).casefold()),
    )
    selected = entries[request.offset : request.offset + request.limit]
    public: list[dict[str, Any]] = []
    for entry in selected:
        result_id = canonical_result_id(str(entry.get("result_id") or entry.get("id") or ""))
        path = Path(paths.result_file(result_id))
        source_kind = str(entry.get("origin") or result_id.partition(":")[0] or "unknown")
        public.append(
            {
                "result_id": result_id,
                "name": str(entry.get("name") or Path(result_id).name),
                "kind": str(entry.get("suffix") or Path(result_id).suffix).lstrip(".").casefold(),
                "source_sha256": _stable_hash(path),
                "lineage": {"source_kind": source_kind, "source_id": result_id},
            }
        )
    total = len(entries)
    return {
        "results": public,
        "total_results": total,
        "returned_results": len(public),
        "offset": request.offset,
        "limit": request.limit,
        "truncated": request.offset + len(public) < total,
        "workspace_generation": int(snapshot.get("generation", 0)),
    }


def _page_indices(size: int, offset: int, limit: int, strategy: str) -> list[int]:
    available = list(range(min(offset, size), size))
    if len(available) <= limit:
        return available
    match strategy:
        case "head":
            return available[:limit]
        case "tail":
            return available[-limit:]
        case "uniform":
            if limit == 1:
                return available[:1]
            last = len(available) - 1
            return [available[round(index * last / (limit - 1))] for index in range(limit)]
        case _:
            raise ToolError("Unknown result truncation strategy.")


def series(args: dict[str, Any], paths: PathBindings = DEFAULT_PATHS) -> dict[str, Any]:
    """Return one numeric result series under an explicit row budget."""
    try:
        request = _SeriesRequest.model_validate(args)
    except ValidationError as exc:
        raise ToolError("Invalid results_series arguments or row_limit.") from exc
    if request.time_range is not None and request.time_range.start > request.time_range.end:
        raise ToolError("Result time range start must not exceed end.")
    result_id = canonical_result_id(request.result_id)
    path = Path(paths.result_file(result_id))
    before = results.file_sha256(path)
    options: dict[str, Any] = {
        "value_unit": request.value_unit,
        "time_unit": request.time_unit,
        "quantity_kind": request.quantity_kind,
    }
    if request.time_range is not None:
        options["range_spec"] = {
            "mode": "bounds",
            "start": request.time_range.start,
            "end": request.time_range.end,
        }
    payload = results.variable_series(
        str(path), request.variable, request.position, **options
    )
    after = ensure_result_source_unchanged(path, before, results.file_sha256)
    times = payload.get("time")
    values = payload.get("values")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise ToolError("Result series has inconsistent numeric rows.")
    numeric_times = _finite_rows(times, "time")
    numeric_values = _finite_rows(values, "value")
    indices = _page_indices(
        len(numeric_times),
        request.offset,
        min(request.row_limit, MAX_TRANSCRIPT_ROWS),
        request.truncation,
    )
    rows = [
        {"time": numeric_times[index], "value": numeric_values[index]}
        for index in indices
    ]
    return {
        "result_id": result_id,
        "rows": rows,
        "variable": request.variable,
        "row_limit": request.row_limit,
        "total_rows": len(numeric_times),
        "returned_rows": len(rows),
        "units": {"time": payload.get("time_unit"), "value": payload.get("unit")},
        "position": payload.get("position"),
        "time_range": {"start": min(numeric_times), "end": max(numeric_times)},
        "source_sha256": after,
        "truncated": len(rows) < len(numeric_times),
        "truncation": request.truncation,
        "analysis": payload.get("analysis") or {},
        "lineage": {
            "source_kind": result_id.partition(":")[0],
            "source_id": result_id,
        },
    }


def profile(args: dict[str, Any], paths: PathBindings = DEFAULT_PATHS) -> dict[str, Any]:
    """Return one variable along one .ppl branch at one time (default: the last)."""
    result_id = canonical_result_id(str(args["result_id"]))
    path = Path(paths.result_file(result_id))
    if path.suffix.casefold() != ".ppl":
        raise ToolError("results_profile reads .ppl profiles; use results_series for a .tpl trend.")
    before = results.file_sha256(path)
    payload = results.variable_profile(
        str(path), str(args["variable"]), str(args["branch"]), args.get("timestep")
    )
    raw_positions = payload.get("positions") or []
    raw_values = payload.get("values") or []
    if len(raw_positions) != len(raw_values):
        raise ToolError("Result profile has inconsistent numeric rows.")
    # The parser writes an undefined section (NaN) as null; skip it and say how many.
    defined = [(p, v) for p, v in zip(raw_positions, raw_values) if p is not None and v is not None]
    if not defined:
        raise ToolError("Result profile has no defined values at this time.")
    positions = _finite_rows([p for p, _ in defined], "position")
    values = _finite_rows([v for _, v in defined], "value")
    peak = max(range(len(values)), key=values.__getitem__)
    low = min(range(len(values)), key=values.__getitem__)
    indices = _page_indices(len(values), 0, MAX_TRANSCRIPT_ROWS, "uniform")
    timesteps = [float(t) for t in results.load_result(str(path)).get("timesteps") or []]
    change = _change_since_previous(
        path, args, payload.get("timestep"), timesteps, dict(zip(positions, values))
    )
    after = ensure_result_source_unchanged(path, before, results.file_sha256)
    return {
        "result_id": result_id,
        "variable": payload.get("variable", args["variable"]),
        "branch": payload.get("branch", args["branch"]),
        "timestep": payload.get("timestep"),
        "timestep_unit": payload.get("timestep_unit"),
        "rows": [{"position": positions[i], "value": values[i]} for i in indices],
        "total_rows": len(values),
        "skipped_rows": len(raw_values) - len(values),
        "truncated": len(indices) < len(values),
        "units": {"position": "m", "value": payload.get("unit")},
        "maximum": {"position": positions[peak], "value": values[peak]},
        "minimum": {"position": positions[low], "value": values[low]},
        # The first saved time and the newest ones; the full list can overflow the result cap.
        "timesteps": timesteps[:1] + timesteps[1:][-(MAX_LISTED_TIMESTEPS - 1):],
        "timestep_count": len(timesteps),
        "change_since_previous": change,
        "source_sha256": after,
        "lineage": {"source_kind": result_id.partition(":")[0], "source_id": result_id},
    }


def _change_since_previous(
    path: Path,
    args: dict[str, Any],
    selected: Any,
    timesteps: list[float],
    current: dict[float, float],
) -> dict[str, Any] | None:
    """The largest change from the previous saved profile; a large one means still developing."""
    if not isinstance(selected, (int, float)):
        return None
    earlier = [t for t in timesteps if t < float(selected) - 1e-9]
    if not earlier:
        return None
    previous_time = earlier[-1]
    try:
        previous = results.variable_profile(
            str(path), str(args["variable"]), str(args["branch"]), previous_time
        )
    except Exception:  # the comparison is optional; the requested profile still stands
        return None
    pairs = [
        (position, abs(current[position] - float(value)))
        for position, value in zip(previous.get("positions") or [], previous.get("values") or [])
        if position in current and isinstance(value, (int, float)) and math.isfinite(value)
    ]
    if not pairs:
        return None
    at_position, largest = max(pairs, key=lambda pair: pair[1])
    return {"previous_timestep": previous_time, "max_change": largest, "at_position": at_position}


def _finite_rows(values: list[Any], label: str) -> list[float]:
    numeric: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolError(f"Result {label} rows must be numeric.")
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ToolError(f"Result {label} rows must be finite.")
        numeric.append(parsed)
    if not numeric:
        raise ToolError("Result series contains no rows.")
    return numeric
