from __future__ import annotations

import csv
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .genkey_static import CommandResult, OlgaInputError
from .result_export_paths import ExportsRoot, create_export_dir, safe_export_token
from .result_provenance import ensure_result_source_unchanged

HashFile = Callable[[Path], str]
ResolveResult = Callable[[str], Path]
RunTool = Callable[..., CommandResult]
SeriesReader = Callable[..., dict[str, Any]]
TokenValidator = Callable[[list[str], str], list[str]]


def export_selected_series_csv(
    path_value: str,
    variable: str,
    position: str,
    *,
    value_unit: str | None,
    time_unit: str | None,
    quantity_kind: str,
    range_spec: dict[str, Any] | None,
    resolve_result: ResolveResult,
    hash_file: HashFile,
    exports_root: ExportsRoot,
    series_reader: SeriesReader,
) -> dict[str, Any]:
    """Export exactly one validated position-selected series."""
    path = resolve_result(path_value)
    before = hash_file(path)
    view_requested = (
        value_unit is not None
        or time_unit is not None
        or quantity_kind != "point"
        or range_spec is not None
    )
    requested_value_unit = value_unit
    requested_time_unit = time_unit
    if view_requested:
        series = series_reader(
            path_value,
            variable,
            position,
            value_unit=value_unit,
            time_unit=time_unit,
            quantity_kind=quantity_kind,
            range_spec=range_spec,
        )
    else:
        series = series_reader(path_value, variable, position)
    times = series.get("time")
    values = series.get("values")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise OlgaInputError("Selected result series has inconsistent time and value rows.")

    out_dir = create_export_dir(exports_root)
    safe_variable = safe_export_token(variable, "variable")
    safe_position = safe_export_token(series.get("position") or position, "position")
    series_label = f"{safe_variable}@{safe_position}"
    csv_path = out_dir / f"selected-series-{safe_variable}-{safe_position}-{uuid.uuid4().hex}.csv"
    resolved_time_unit = series.get("time_unit")
    time_header = f"time_{resolved_time_unit}" if resolved_time_unit else "time"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([time_header, series_label])
        writer.writerows(zip(times, values, strict=True))

    after = ensure_result_source_unchanged(path, before, hash_file, discard_root=out_dir)
    provenance = {
        "kind": "selected_series",
        "source_path": str(path),
        "source_sha256": before,
        "variable": variable,
        "requested_position": position,
        "position": series.get("position"),
        "unit": series.get("unit"),
        "time_unit": resolved_time_unit,
        "safe_variable": safe_variable,
        "safe_position": safe_position,
    }
    if view_requested:
        provenance["view"] = {
            "value_unit": requested_value_unit,
            "time_unit": requested_time_unit,
            "quantity_kind": quantity_kind,
            "range": range_spec or {"mode": "full"},
        }
    return {
        "path": str(path),
        "ok": True,
        "csv": str(csv_path),
        "download_path": str(csv_path),
        "download_name": csv_path.name,
        "series_label": series_label,
        "variable": series.get("variable") or variable,
        "position": series.get("position"),
        "unit": series.get("unit"),
        "time_unit": resolved_time_unit,
        "view": series.get("view"),
        "row_count": len(times),
        "provenance": provenance,
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": before != after,
    }


def extract_csv(
    path_value: str,
    variables: list[str],
    branch: str | None,
    timestep: float | None,
    *,
    resolve_result: ResolveResult,
    hash_file: HashFile,
    exports_root: ExportsRoot,
    require_tokens: TokenValidator,
    run_tool: RunTool,
    result_scripts: dict[str, str],
) -> dict[str, Any]:
    path = resolve_result(path_value)
    names = require_tokens(variables, "variable")
    before = hash_file(path)
    out_dir = create_export_dir(exports_root)
    csv_path = out_dir / "export.csv"
    args = [str(path), "--variables", ",".join(names), "-o", str(csv_path)]
    if branch:
        args.extend(["--branch", require_tokens([branch], "branch")[0]])
    if timestep is not None:
        args.extend(["--timestep", str(timestep)])
    command = run_tool("data_exporter", args, names=result_scripts)
    ok = command.exit_code == 0 and csv_path.exists()
    after = ensure_result_source_unchanged(path, before, hash_file, discard_root=out_dir)
    return {
        "path": str(path),
        "ok": ok,
        "csv": str(csv_path) if ok else None,
        "command": command.to_dict(),
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": before != after,
    }
