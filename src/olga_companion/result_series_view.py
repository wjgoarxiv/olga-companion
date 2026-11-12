from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .publication_plot import interpret_series
from .units import convert_values


@dataclass(frozen=True, slots=True)
class ResultSeriesViewError(ValueError):
    """A result series cannot satisfy the requested view contract."""

    message: str

    def __str__(self) -> str:
        return self.message


def apply_series_view(
    time: list[float],
    values: list[float],
    *,
    source_unit: str | None,
    source_time_unit: str | None,
    value_unit: str | None = None,
    time_unit: str | None = None,
    quantity_kind: str = "point",
    range_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one validated, converted, filtered copy used by chart and analysis."""
    if len(time) != len(values):
        raise ResultSeriesViewError("Selected result series has inconsistent time and value rows.")
    if not time:
        raise ResultSeriesViewError("The selected result series has no samples.")

    converted_time = convert_values(time, source_time_unit, time_unit)
    converted_values = convert_values(values, source_unit, value_unit, quantity_kind=quantity_kind)
    times = converted_time["values"]
    data = converted_values["values"]
    if any(later < earlier for earlier, later in zip(times, times[1:], strict=False)):
        raise ResultSeriesViewError("Result time samples must be non-decreasing.")

    spec = dict(range_spec or {"mode": "full"})
    mode = spec.get("mode", "full")
    if mode not in {"full", "tail", "bounds"}:
        raise ResultSeriesViewError("Result range mode must be 'full', 'tail', or 'bounds'.")
    if mode == "full":
        if set(spec) - {"mode"}:
            raise ResultSeriesViewError("A full result range accepts only the mode field.")
        selected = list(range(len(times)))
        range_metadata: dict[str, Any] = {"mode": "full"}
    elif mode == "tail":
        if set(spec) - {"mode", "fraction"} or "fraction" not in spec:
            raise ResultSeriesViewError("A tail result range requires only a fraction field.")
        try:
            fraction = float(spec["fraction"])
        except (TypeError, ValueError) as exc:
            raise ResultSeriesViewError("Tail range fraction must be numeric and finite.") from exc
        if not math.isfinite(fraction):
            raise ResultSeriesViewError("Tail range fraction must be finite.")
        if not 0.0 < fraction <= 1.0:
            raise ResultSeriesViewError("Tail range fraction must be greater than zero and at most one.")
        start = min(times) + (max(times) - min(times)) * (1.0 - fraction)
        selected = [index for index, sample_time in enumerate(times) if sample_time >= start]
        range_metadata = {"mode": "tail", "fraction": fraction}
    else:
        if set(spec) - {"mode", "start", "end"} or not {"start", "end"} <= set(spec):
            raise ResultSeriesViewError("A bounds result range requires only start and end fields.")
        try:
            start = float(spec["start"])
            end = float(spec["end"])
        except (TypeError, ValueError) as exc:
            raise ResultSeriesViewError("Result range bounds must be numeric and finite.") from exc
        if not math.isfinite(start) or not math.isfinite(end):
            raise ResultSeriesViewError("Result range bounds must be finite.")
        if start > end:
            raise ResultSeriesViewError("Result range bounds are reversed.")
        selected = [index for index, sample_time in enumerate(times) if start <= sample_time <= end]
        range_metadata = {"mode": "bounds", "start": start, "end": end}

    if not selected:
        raise ResultSeriesViewError("The selected result range contains no samples.")
    selected_time = [times[index] for index in selected]
    selected_values = [data[index] for index in selected]
    range_metadata.update(
        {
            "start": min(selected_time),
            "end": max(selected_time),
            "samples": len(selected_time),
        }
    )
    return {
        "time": selected_time,
        "values": selected_values,
        "unit": converted_values["unit"],
        "time_unit": converted_time["unit"],
        "analysis": interpret_series(selected_time, selected_values),
        "view": {
            "value_conversion": converted_values["conversion"],
            "time_conversion": converted_time["conversion"],
            "range": range_metadata,
        },
    }
