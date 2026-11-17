"""One property of a .tab as a pressure x temperature matrix, for the workspace preview (read-only)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .genkey_static import OlgaInputError
from .tab_compare import GridMismatchError, _parse

# The parse runs in-process with no timeout, so the preview takes a smaller file than the toolkit does.
MAX_GRID_BYTES = 8 * 1024 * 1024
MAX_AXIS = 64
MAX_CURVE = 200
_AXES = {"PT", "TM"}
_TO_PA = {"PA": 1.0, "KPA": 1e3, "MPA": 1e6, "BAR": 1e5, "BARA": 1e5}


def _sample(count: int, limit: int = MAX_AXIS) -> list[int]:
    """Evenly spaced indices that always keep the first and last point."""
    if count <= limit:
        return list(range(count))
    step = (count - 1) / (limit - 1)
    return sorted({round(i * step) for i in range(limit)})


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def _unit(parsed: Any, key: str) -> str:
    field = parsed._pairs.get(key)
    return str(field.get("unit") or "").strip().upper() if isinstance(field, dict) else ""


def _numbers(parsed: Any, key: str) -> list[float]:
    field = parsed._pairs.get(key)
    value = field.get("value") if isinstance(field, dict) else field
    if not isinstance(value, list):
        value = [value]
    return [float(v) for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _to_pa(value: float, unit: str) -> float | None:
    return _finite(value * _TO_PA.get(unit, 1.0))


def _to_c(value: float, unit: str) -> float | None:
    if unit == "K":
        value -= 273.15
    elif unit == "F":
        value = (value - 32.0) * 5.0 / 9.0
    return _finite(value)


def _curve(pressures: list[float], temperatures: list[float], p_unit: str, t_unit: str) -> list[list[float | None]]:
    """[p_pa, t_c] pairs; a pressure without a temperature (or the reverse) is dropped, a non-finite number is null."""
    return [[_to_pa(p, p_unit), _to_c(t, t_unit)] for p, t in zip(pressures, temperatures)]


def _cap_curve(points: list[list[float | None]]) -> list[list[float | None]]:
    """At most MAX_CURVE points, always keeping the first, the last and the extremes of both axes."""
    if len(points) <= MAX_CURVE:
        return points
    keep = {0, len(points) - 1}
    for axis in (0, 1):
        known = [i for i, point in enumerate(points) if point[axis] is not None]
        if known:
            keep.add(min(known, key=lambda i: points[i][axis]))
            keep.add(max(known, key=lambda i: points[i][axis]))
    keep.update(_sample(len(points), MAX_CURVE - len(keep)))
    return [points[i] for i in sorted(keep)]


def _envelope(parsed: Any) -> dict[str, Any]:
    """Bubble and dew curves plus the critical point in P-T, in Pa and degrees C; empty when the file has none."""
    curves = {}
    for label, p_key, t_key in (("bubble", "BUBBLEPRESSURES", "BUBBLETEMPERATURES"), ("dew", "DEWPRESSURES", "DEWTEMPERATURES")):
        curves[label] = _cap_curve(_curve(_numbers(parsed, p_key), _numbers(parsed, t_key), _unit(parsed, p_key), _unit(parsed, t_key)))
    critical = None
    cp, ct = _numbers(parsed, "CRITICALPRESSURE"), _numbers(parsed, "CRITICALTEMPERATURE")
    if cp and ct:
        p_pa, t_c = _to_pa(cp[0], _unit(parsed, "CRITICALPRESSURE")), _to_c(ct[0], _unit(parsed, "CRITICALTEMPERATURE"))
        if p_pa is not None and t_c is not None:
            critical = {"p_pa": p_pa, "t_c": t_c}
    return {**curves, "critical": critical}


def _legacy_points(parsed: Any, name: str, pressures: list[float]) -> list[list[float | None]]:
    """The flat property array split into one list of point values per pressure."""
    flat = parsed.get_property(name) or []
    counts = parsed.n_enthalpies
    if len(counts) != len(pressures) or sum(counts) != len(flat):
        counts = [len(flat) // len(pressures)] * len(pressures) if flat and len(flat) % len(pressures) == 0 else []
    if not counts:
        raise OlgaInputError(f"{name} does not split into one list of values per pressure.")
    rows, start = [], 0
    for count in counts:
        rows.append([_finite(float(v)) for v in flat[start:start + count]])
        start += count
    return rows


def tab_grid(path_value: str, column: str | None = None) -> dict[str, Any]:
    path = Path(path_value)
    if path.stat().st_size > MAX_GRID_BYTES:
        raise OlgaInputError(f"{path.name} is too large to preview (the limit is {MAX_GRID_BYTES} bytes).")
    try:
        parsed = _parse(path)
    except GridMismatchError as exc:
        raise OlgaInputError(str(exc)) from exc
    envelope = _envelope(parsed)
    base = {"path": str(path), "label": parsed.label, "phase": parsed.phase}
    properties = [name for name in parsed.columns if name not in _AXES]
    if not properties or parsed.point_rows is None:
        # Legacy tables keep flat arrays with no temperature axis; no P x T grid is invented for them.
        legacy = [name for name in parsed.available_properties if name not in _AXES]
        if not legacy or not parsed.pressure_grid:
            raise OlgaInputError(f"{path.name} has no PVT property data to preview.")
        name = (column or legacy[0]).upper()
        if name not in legacy:
            raise OlgaInputError(f"{name} is not a property of {path.name}.")
        every = [float(p) for p in parsed.pressure_grid]
        rows = _legacy_points(parsed, name, every)
        p_keep = _sample(len(every))
        width = max((len(row) for row in rows), default=0)
        w_keep = _sample(width)
        return {**base, "format": "legacy", "properties": legacy, "column": name,
                "pressures": [every[i] for i in p_keep], "temperatures": [], "values": None,
                "points": [[rows[i][j] if j < len(rows[i]) else None for j in w_keep] for i in p_keep],
                "pointIndexes": w_keep, "unit": _unit(parsed, name), "envelope": envelope,
                "downsampled": len(p_keep) < len(every) or len(w_keep) < width, "shape": [len(every), width]}
    name = (column or properties[0]).upper()
    if name not in properties:
        raise OlgaInputError(f"{name} is not a column of {path.name}.")
    pressures, temperatures = parsed.pressure_grid, parsed.temperature_grid
    p_at, t_at, v_at = (parsed.columns.index(key) for key in ("PT", "TM", name))
    lookup = {(row[p_at], row[t_at]): row[v_at] for row in parsed.point_rows}
    p_keep, t_keep = _sample(len(pressures)), _sample(len(temperatures))
    p_unit, t_unit = _unit(parsed, "PRESSURE"), _unit(parsed, "TEMPERATURE")
    return {
        **base,
        "format": "standard",
        "properties": properties,
        "column": name,
        "pressures": [_to_pa(float(pressures[i]), p_unit) for i in p_keep],
        "temperatures": [_to_c(float(temperatures[j]), t_unit) for j in t_keep],
        "values": [[_finite(lookup.get((pressures[i], temperatures[j]))) for j in t_keep] for i in p_keep],
        "downsampled": len(p_keep) < len(pressures) or len(t_keep) < len(temperatures),
        "shape": [len(pressures), len(temperatures)],
        "envelope": envelope,
    }
