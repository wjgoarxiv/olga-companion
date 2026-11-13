from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable


class UnitConversionError(ValueError):
    """Raised when a requested unit conversion cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class _Unit:
    dimension: str
    scale: float
    offset: float = 0.0


# Scale and offset convert a value to the dimension's SI base. Temperature
# offsets apply only to point values; explicit delta conversions use scale only.
UNIT_REGISTRY: dict[str, _Unit] = {
    "Pa": _Unit("pressure", 1.0),
    "kPa": _Unit("pressure", 1_000.0),
    "MPa": _Unit("pressure", 1_000_000.0),
    "bar": _Unit("pressure", 100_000.0),
    "psi": _Unit("pressure", 6_894.757293168),
    "K": _Unit("temperature", 1.0),
    "C": _Unit("temperature", 1.0, 273.15),
    "F": _Unit("temperature", 5.0 / 9.0, 255.3722222222222),
    "s": _Unit("time", 1.0),
    "min": _Unit("time", 60.0),
    "h": _Unit("time", 3_600.0),
    "kg/s": _Unit("mass_flow", 1.0),
    "kg/h": _Unit("mass_flow", 1.0 / 3_600.0),
    "t/h": _Unit("mass_flow", 1_000.0 / 3_600.0),
    "lb/h": _Unit("mass_flow", 0.45359237 / 3_600.0),
    "m3/s": _Unit("volume_flow", 1.0),
    "m3/h": _Unit("volume_flow", 1.0 / 3_600.0),
    "L/s": _Unit("volume_flow", 0.001),
    "m": _Unit("length", 1.0),
    "mm": _Unit("length", 0.001),
    "km": _Unit("length", 1_000.0),
    "ft": _Unit("length", 0.3048),
    "m/s": _Unit("velocity", 1.0),
    "ft/s": _Unit("velocity", 0.3048),
    "fraction": _Unit("dimensionless", 1.0),
    "%": _Unit("dimensionless", 0.01),
}

_ALIASES = {name.casefold(): name for name in UNIT_REGISTRY}
_ALIASES["-"] = "fraction"
_EXPLICIT_PRESSURE_REFERENCES = {"barg", "psig", "bara", "psia"}
_UNIT_TEXT = re.compile(r"^[A-Za-z0-9%°_./*^+ -]+$")


def _validate_unit_text(unit: str | None, *, role: str, allow_none: bool = False) -> str | None:
    if unit is None and allow_none:
        return None
    if not isinstance(unit, str):
        raise UnitConversionError(f"{role} unit must be a string.")
    if not unit or len(unit) > 64 or unit != unit.strip() or not _UNIT_TEXT.fullmatch(unit):
        raise UnitConversionError(f"Malformed {role} unit: {unit!r}")
    return unit


def _metadata(
    *,
    status: str,
    source_unit: str | None,
    requested_unit: str | None,
    output_unit: str | None,
    quantity_kind: str,
    dimension: str | None,
    reason: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "source_unit": source_unit,
        "requested_unit": requested_unit,
        "output_unit": output_unit,
        "dimension": dimension,
        "quantity_kind": quantity_kind,
        "reason": reason,
    }
    if dimension == "pressure":
        result["reference_semantics"] = "preserved"
    return result


def convert_values(
    values: Iterable[float],
    source_unit: str | None,
    requested_unit: str | None,
    *,
    quantity_kind: str = "point",
) -> dict[str, Any]:
    """Convert a copied value sequence using the conservative OLGA allowlist.

    Unknown, incompatible, and reference-explicit pressure units are returned
    unchanged with ``source_only`` metadata. Invalid unit text and non-finite
    numeric data are rejected rather than guessed or silently dropped.
    """
    if quantity_kind not in {"point", "delta"}:
        raise UnitConversionError("quantity_kind must be 'point' or 'delta'.")
    source = _validate_unit_text(source_unit, role="source", allow_none=True)
    requested = _validate_unit_text(requested_unit, role="requested", allow_none=True)
    copied = list(values)
    try:
        numeric = [float(value) for value in copied]
    except (TypeError, ValueError) as exc:
        raise UnitConversionError("Series values must be numeric and finite.") from exc
    if not all(math.isfinite(value) for value in numeric):
        raise UnitConversionError("Series values must be finite.")

    source_key = source.casefold() if source is not None else None
    requested_key = requested.casefold() if requested is not None else None
    source_name = _ALIASES.get(source_key) if source_key is not None else None
    requested_name = _ALIASES.get(requested_key) if requested_key is not None else None
    source_def = UNIT_REGISTRY.get(source_name) if source_name is not None else None
    requested_def = UNIT_REGISTRY.get(requested_name) if requested_name is not None else None

    if requested is None:
        return {
            "values": copied,
            "unit": source,
            "conversion": _metadata(
                status="not_requested",
                source_unit=source,
                requested_unit=None,
                output_unit=source,
                quantity_kind=quantity_kind,
                dimension=source_def.dimension if source_def else None,
                reason=None,
            ),
        }
    if source_key in _EXPLICIT_PRESSURE_REFERENCES or requested_key in _EXPLICIT_PRESSURE_REFERENCES:
        reason = "explicit_pressure_reference_requires_metadata"
    elif source_def is None:
        reason = "unknown_source_unit"
    elif requested_def is None:
        reason = "unknown_requested_unit"
    elif source_def.dimension != requested_def.dimension:
        reason = "incompatible_dimensions"
    else:
        reason = None
    if reason is not None:
        return {
            "values": copied,
            "unit": source,
            "conversion": _metadata(
                status="source_only",
                source_unit=source,
                requested_unit=requested,
                output_unit=source,
                quantity_kind=quantity_kind,
                dimension=source_def.dimension if source_def else None,
                reason=reason,
            ),
        }

    if source == requested:
        assert source_def is not None and requested_name is not None
        return {
            "values": copied,
            "unit": requested_name,
            "conversion": _metadata(
                status="identity",
                source_unit=source,
                requested_unit=requested,
                output_unit=requested_name,
                quantity_kind=quantity_kind,
                dimension=source_def.dimension,
                reason=None,
            ),
        }

    assert source_def is not None and requested_def is not None and requested_name is not None
    converted: list[float] = []
    for value in numeric:
        if source_def.dimension == "temperature" and quantity_kind == "point":
            base_value = value * source_def.scale + source_def.offset
            output_value = (base_value - requested_def.offset) / requested_def.scale
        else:
            base_value = value * source_def.scale
            output_value = base_value / requested_def.scale
        if not math.isfinite(output_value):
            raise UnitConversionError("Converted series values must be finite.")
        converted.append(output_value)
    return {
        "values": converted,
        "unit": requested_name,
        "conversion": _metadata(
            status="converted",
            source_unit=source,
            requested_unit=requested,
            output_unit=requested_name,
            quantity_kind=quantity_kind,
            dimension=source_def.dimension,
            reason=None,
        ),
    }
