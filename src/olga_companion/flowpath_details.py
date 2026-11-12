from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Any
from .genkey_static import (
    FLOWPATH_TOOL_OUTPUT_BYTES,
    TOOL_OUTPUT_LIMIT_EXIT_CODE,
    OlgaInputError,
    pipe_geometry,
    run_tool,
)
from .units import UnitConversionError, convert_values
MAX_FLOWPATH_PIPES = 500
MAX_FLOWPATH_SECTIONS = 5_000
class _GeometryUnavailable(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OlgaInputError(f"Flowpath geometry returned an invalid {field} value.")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise OlgaInputError(f"Flowpath geometry returned an invalid {field} value.")
    return result
def _pipe_record(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise OlgaInputError("Flowpath geometry returned an invalid pipe record.")
    label = raw.get("label")
    if not isinstance(label, str) or not label or len(label) > 256:
        raise OlgaInputError("Flowpath geometry returned an invalid pipe label.")
    nsegment = raw.get("nsegment")
    if isinstance(nsegment, bool) or not isinstance(nsegment, int) or nsegment < 0:
        raise OlgaInputError("Flowpath geometry returned an invalid segment count.")
    section_range = raw.get("section_range")
    if (
        not isinstance(section_range, list)
        or len(section_range) != 2
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in section_range)
        or section_range[0] < 0
        or section_range[1] < section_range[0]
    ):
        raise OlgaInputError("Flowpath geometry returned an invalid section range.")
    return {
        "label": label,
        "nsegment": nsegment,
        "diameter_m": _number(raw.get("diameter_m"), "diameter"),
        "total_length_m": _number(raw.get("total_length_m"), "length"),
        "volume_m3": _number(raw.get("volume_m3"), "volume"),
        "section_range": section_range,
    }
def _aggregate_number(pipes: list[dict[str, Any]], key: str, field: str) -> float:
    return _number(sum(pipe[key] for pipe in pipes), f"aggregate {field}")
def _summary(pipes: list[dict[str, Any]]) -> dict[str, Any]:
    diameters = [pipe["diameter_m"] for pipe in pipes]
    return {
        "pipe_count": len(pipes),
        "segment_count": sum(pipe["nsegment"] for pipe in pipes),
        "total_length_m": _aggregate_number(pipes, "total_length_m", "length"),
        "total_volume_m3": _aggregate_number(pipes, "volume_m3", "volume"),
        "diameter_min_m": min(diameters) if diameters else None,
        "diameter_max_m": max(diameters) if diameters else None,
    }


def _metres(raw: Any, reason: str) -> list[float]:
    if not isinstance(raw, dict) or "value" not in raw:
        raise _GeometryUnavailable("missing_coordinates" if reason == "coordinate" else reason)
    values = raw["value"] if isinstance(raw["value"], list) else [raw["value"]]
    if any(value is None for value in values):
        raise _GeometryUnavailable("missing_coordinates" if reason == "coordinate" else reason)
    try:
        converted = convert_values(values, raw.get("unit"), "m")
    except (UnitConversionError, TypeError, ValueError):
        raise _GeometryUnavailable(
            "non_finite_coordinates" if reason == "coordinate" else reason
        ) from None
    if converted.get("unit") != "m":
        raise _GeometryUnavailable("unknown_length_unit")
    result = converted.get("values")
    if not isinstance(result, list) or not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in result
    ):
        raise _GeometryUnavailable(
            "non_finite_coordinates" if reason == "coordinate" else reason
        )
    return [float(value) for value in result]


def _point(params: dict[str, Any], suffix: str) -> dict[str, float]:
    values = [
        _scalar_metres(params.get(f"{axis}{suffix}"), "coordinate")
        for axis in ("X", "Y", "Z")
    ]
    return dict(zip(("x_m", "y_m", "z_m"), values, strict=True))


def _scalar_metres(raw: Any, reason: str) -> float:
    values = _metres(raw, reason)
    if len(values) != 1:
        raise _GeometryUnavailable(
            "invalid_coordinate_cardinality" if reason == "coordinate" else reason
        )
    return values[0]


def _signed_metres(raw: Any) -> float:
    """ELEVATION may be negative; the coordinate readers accept any finite sign."""
    values = _metres(raw, "missing_coordinates")
    if len(values) != 1:
        raise _GeometryUnavailable("missing_coordinates")
    return values[0]


def _distance(start: dict[str, float], end: dict[str, float]) -> float:
    return math.sqrt(sum((end[axis] - start[axis]) ** 2 for axis in start))


def _interpolate(
    start: dict[str, float], end: dict[str, float], fraction: float
) -> dict[str, float]:
    return {axis: start[axis] + ((end[axis] - start[axis]) * fraction) for axis in start}


def _parser_document(path: Path) -> dict[str, Any]:
    result = run_tool(
        "parser",
        [str(path), "--json", "--compact"],
        max_output_bytes=FLOWPATH_TOOL_OUTPUT_BYTES,
    )
    if result.exit_code == TOOL_OUTPUT_LIMIT_EXIT_CODE:
        raise OlgaInputError("Flowpath geometry exceeds the supported output limit.")
    if result.exit_code != 0:
        raise OlgaInputError("Flowpath geometry could not be read from the selected case.")
    try:
        parsed = json.loads(result.stdout)
    except (json.JSONDecodeError, RecursionError):
        raise OlgaInputError("Flowpath parser output was invalid.") from None
    if not isinstance(parsed, dict):
        raise OlgaInputError("Flowpath parser output was invalid.")
    return parsed


def _flowpath_children(document: dict[str, Any], flowpath: str) -> list[dict[str, Any]]:
    records = document.get("flowpaths")
    if not isinstance(records, list):
        raise OlgaInputError("Flowpath parser output was invalid.")
    record = next(
        (item for item in records if isinstance(item, dict) and item.get("tag") == flowpath),
        None,
    )
    children = record.get("children") if isinstance(record, dict) else None
    if not isinstance(children, list) or not all(isinstance(item, dict) for item in children):
        raise OlgaInputError("The requested flowpath could not be read from the selected case.")
    return children


def _geometry_response(
    children: list[dict[str, Any]], flowpath: str
) -> dict[str, Any]:
    pipe_children = [item for item in children if item.get("keyword") == "PIPE"]
    if len(pipe_children) > MAX_FLOWPATH_PIPES:
        raise OlgaInputError("Flowpath geometry exceeds the supported pipe limit.")
    geometry = next((item for item in children if item.get("keyword") == "GEOMETRY"), None)
    if not isinstance(geometry, dict) or not isinstance(geometry.get("params"), dict):
        raise _GeometryUnavailable("missing_coordinates")
    # A flowpath given as pipe LENGTH and ELEVATION has no coordinates; it is drawn as a
    # profile from the origin, horizontal run along x and height on the viewer's y axis.
    from_lengths = "XSTART" not in geometry["params"] and all(
        isinstance(item.get("params"), dict) and "LENGTH" in item["params"] and "XEND" not in item["params"]
        for item in pipe_children
    ) and bool(pipe_children)
    current = {"x_m": 0.0, "y_m": 0.0, "z_m": 0.0} if from_lengths else _point(geometry["params"], "START")
    geometry_start = dict(current)
    pipes: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    chainage = 0.0
    for child in pipe_children:
        params = child.get("params")
        if not isinstance(params, dict):
            raise _GeometryUnavailable("missing_coordinates")
        label = params.get("LABEL")
        nsegment = params.get("NSEGMENT")
        if not isinstance(label, str) or not label or len(label) > 256:
            raise OlgaInputError("Flowpath geometry returned an invalid pipe label.")
        lengths = _metres(params.get("LSEGMENT"), "invalid_section_lengths")
        if isinstance(nsegment, bool) or not isinstance(nsegment, int) or nsegment < 1 or nsegment != len(lengths):
            raise _GeometryUnavailable("section_count_mismatch")
        if len(sections) + nsegment > MAX_FLOWPATH_SECTIONS:
            raise OlgaInputError("Flowpath geometry exceeds the supported section limit.")
        if any(length < 0 for length in lengths):
            raise _GeometryUnavailable("invalid_section_lengths")
        diameter = _scalar_metres(params.get("DIAMETER"), "invalid_diameter")
        if diameter < 0:
            raise _GeometryUnavailable("invalid_diameter")
        if from_lengths:
            pipe_length = _scalar_metres(params.get("LENGTH"), "missing_coordinates")
            rise = _signed_metres(params.get("ELEVATION"))
            run = math.sqrt(max(pipe_length * pipe_length - rise * rise, 0.0))
            end = {"x_m": current["x_m"] + run, "y_m": current["y_m"] + rise, "z_m": current["z_m"]}
        else:
            end = _point(params, "END")
        total_length = sum(lengths)
        if abs(_distance(current, end) - total_length) > max(0.05, total_length * 0.01):
            raise _GeometryUnavailable("length_endpoint_mismatch")
        first_section = len(sections)
        travelled = 0.0
        for local_index, length in enumerate(lengths, start=1):
            section_start = _interpolate(current, end, travelled / total_length) if total_length else dict(current)
            travelled += length
            section_end = dict(end) if local_index == nsegment else _interpolate(current, end, travelled / total_length)
            sections.append({
                "section_index": len(sections),
                "pipe_section_index": local_index,
                "pipe_label": label,
                "length_m": length,
                "diameter_m": diameter,
                "chainage_start_m": chainage,
                "chainage_end_m": chainage + length,
                "start": section_start,
                "center": _interpolate(section_start, section_end, 0.5),
                "end": section_end,
            })
            chainage += length
        area = math.pi * diameter * diameter / 4
        pipes.append({
            "label": label, "nsegment": nsegment, "diameter_m": diameter,
            "total_length_m": total_length, "volume_m3": area * total_length,
            "section_range": [first_section, len(sections) - 1],
            "start": dict(current), "end": dict(end),
        })
        current = end
    return {
        "schema_version": 2,
        "flowpath": flowpath,
        "geometry": {
            "status": "ready", "coordinate_unit": "m", "start": geometry_start,
            **({"source": "length_elevation"} if from_lengths else {}),
        },
        "summary": _summary(pipes),
        "pipes": pipes,
        "sections": sections,
    }


def load_flowpath_details(path: Path, flowpath: str) -> dict[str, Any]:
    """Return bounded, path-free pipe geometry for one exact flowpath."""
    result = pipe_geometry(str(path), flowpath, "list_pipes")
    raw_pipes = result.get("result")
    if not result.get("ok") or not isinstance(raw_pipes, list):
        raise OlgaInputError("Flowpath geometry could not be read from the selected case.")
    if len(raw_pipes) > MAX_FLOWPATH_PIPES:
        raise OlgaInputError("Flowpath geometry exceeds the supported pipe limit.")
    legacy_pipes = [_pipe_record(raw) for raw in raw_pipes]
    legacy_summary = _summary(legacy_pipes)
    document = _parser_document(path)
    children = _flowpath_children(document, flowpath)
    try:
        return _geometry_response(children, flowpath)
    except _GeometryUnavailable as exc:
        return {
            "schema_version": 2,
            "flowpath": flowpath,
            "geometry": {"status": "unavailable", "reason": exc.reason},
            "summary": legacy_summary,
            "pipes": legacy_pipes,
            "sections": [],
        }
