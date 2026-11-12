"""Adapter between the fluids_generate_tab agent tool and the independent PVT engine.

Local PVT builds only (``OLGA_COMPANION_NATIVE_TAB=1``): nothing imports this module otherwise.
The request keeps the user's own units; the engine works in pascal and degrees Celsius, so
this module converts, asks the engine to refuse everything that needs no flash, and writes the
table. Components, model and grid are explicit user choices; nothing is defaulted.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import fluid_table
from .pvt_engine import SUPPORTED_COMPONENTS, SUPPORTED_EOS, get_component
from .pvt_engine.errors import OverwriteError, PvtEngineError
from .pvt_engine.tab_writer import check_request, fill_report_path, generate_table

MODELS = tuple(SUPPORTED_EOS)
COMPONENTS = tuple(SUPPORTED_COMPONENTS)
# Multiflash sample for each engine EOS. PR78 is the 1978 alpha function;
# the installed sample for that family is PRA (PRA.MFL).
MFL_MODEL = {"PR": "PR", "PR78": "PRA", "SRK": "SRK"}
TABLE_KIND_EN = "Independent table, not Multiflash-identical"
TABLE_KIND_KO = "독립 계산 표 (Multiflash와 같지 않음)"
TABLE_KIND = TABLE_KIND_EN + ". Not qualified for OLGA use; compare before relying on it."
MAX_GRID_POINTS = 100
# Product limit on temperatures x pressures. Measured on the engine (Python 3.11, one core):
# about 0.5 ms per node for a three-component fluid and up to about 9 ms per node for eight
# components, so 2500 nodes take roughly 1 to 25 s here. Even ten times slower that stays far
# inside the 1800 s plan lifetime, and a grid this size is already more than a table needs.
MAX_GRID_NODES = 2500
ATMOSPHERE_PA = 101_325.0
_INWG_PA = 249.08891
_PRESSURE_SCALE: dict[str, tuple[float, float]] = {
    "Pa": (1.0, 0.0),
    "kPa": (1_000.0, 0.0),
    "Mpa": (1_000_000.0, 0.0),
    "bar": (100_000.0, 0.0),
    "barg": (100_000.0, ATMOSPHERE_PA),
    "atm": (ATMOSPHERE_PA, 0.0),
    "atmg": (ATMOSPHERE_PA, ATMOSPHERE_PA),
    "psi": (6_894.757293168, 0.0),
    "psig": (6_894.757293168, ATMOSPHERE_PA),
    "mmHg": (133.322387415, 0.0),
    "inwg": (_INWG_PA, ATMOSPHERE_PA),
    "at": (98_066.5, 0.0),
    "atg": (98_066.5, ATMOSPHERE_PA),
}


class NativeTabError(fluid_table.FluidTableError):
    """A request or an engine refusal the user can correct; nothing was written."""


def to_pascal(values: Sequence[float], unit: str) -> list[float]:
    """Absolute pascal from a supported pressure keyword; a gauge keyword adds one atmosphere."""
    scale, offset = _PRESSURE_SCALE[fluid_table.canonical_pressure_unit(unit)]
    return [float(value) * scale + offset for value in values]


def to_celsius(values: Sequence[float], unit: str) -> list[float]:
    """Degrees Celsius from a supported temperature keyword."""
    canonical = fluid_table.canonical_temperature_unit(unit)
    if canonical == "degC":
        return [float(value) for value in values]
    if canonical == "K":
        return [float(value) - 273.15 for value in values]
    if canonical == "degF":
        return [(float(value) - 32.0) * 5.0 / 9.0 for value in values]
    return [(float(value) - 491.67) * 5.0 / 9.0 for value in values]


def _engine_message(exc: Exception) -> str:
    # The engine offers a clip policy this tool does not expose.
    return str(exc).replace(" or ask for grid_policy='clip'", "")


def _components(raw: object) -> tuple[list[str], list[float]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise NativeTabError("At least one component with a mole fraction is required.")
    names: list[str] = []
    moles: list[float] = []
    for entry in raw:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("name"), str):
            raise NativeTabError("Each component must name an engine component and a mole fraction.")
        try:
            names.append(get_component(entry["name"]).name)
        except PvtEngineError as exc:
            raise NativeTabError(str(exc)) from exc
        fraction = entry.get("mole_fraction")
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not math.isfinite(fraction):
            raise NativeTabError(f"Mole fraction for {entry['name']!r} must be a number.")
        moles.append(float(fraction))
    return names, moles


def canonical_request(args: Mapping[str, Any]) -> dict[str, Any]:
    """Validate everything that needs no file and no flash; the result is the approval payload body."""
    label = fluid_table.validate_label(args.get("fluid_label"))
    model = args.get("model")
    if not isinstance(model, str) or model.strip() not in MODELS:
        raise NativeTabError(
            f"Unknown model {model!r}. The independent engine supports: {', '.join(MODELS)}."
        )
    temperature_unit = fluid_table.canonical_temperature_unit(args.get("temperature_unit"))
    pressure_unit = fluid_table.canonical_pressure_unit(args.get("pressure_unit"))
    temperatures = fluid_table.validate_grid(args.get("temperatures"), "temperature")
    pressures = fluid_table.validate_grid(args.get("pressures"), "pressure")
    if max(len(temperatures), len(pressures)) > MAX_GRID_POINTS:
        raise NativeTabError(f"A grid holds at most {MAX_GRID_POINTS} points per axis.")
    if len(temperatures) * len(pressures) > MAX_GRID_NODES:
        raise NativeTabError(
            f"{len(temperatures)} temperatures x {len(pressures)} pressures is "
            f"{len(temperatures) * len(pressures)} nodes; a table holds at most {MAX_GRID_NODES} nodes. "
            "Use fewer points per axis."
        )
    names, moles = _components(args.get("components"))
    request = {
        "fluid_label": label,
        "components": [{"name": name, "mole_fraction": mole} for name, mole in zip(names, moles)],
        "model": model.strip(),
        "temperatures": temperatures,
        "temperature_unit": temperature_unit,
        "pressures": pressures,
        "pressure_unit": pressure_unit,
    }
    try:
        check_request(names, moles, request["model"], to_pascal(pressures, pressure_unit),
                      to_celsius(temperatures, temperature_unit), label)
    except (PvtEngineError, ValueError) as exc:
        raise NativeTabError(_engine_message(exc)) from exc
    return request


def table_paths(table: Path) -> tuple[Path, Path]:
    """The table and the fill report that the engine writes beside it."""
    return table, fill_report_path(table)


def generate(request: Mapping[str, Any], destination: Path) -> dict[str, Any]:
    """Compute and write the table; every refusal leaves the folder as it was."""
    names = [item["name"] for item in request["components"]]
    moles = [item["mole_fraction"] for item in request["components"]]
    try:
        report = generate_table(
            destination, names, moles, request["model"],
            to_pascal(request["pressures"], request["pressure_unit"]),
            to_celsius(request["temperatures"], request["temperature_unit"]),
            request["fluid_label"],
        )
    except OverwriteError as exc:
        raise NativeTabError(
            f"{destination.name} or its fill report already exists; the engine never overwrites a file."
        ) from exc
    except (PvtEngineError, ValueError, ArithmeticError) as exc:
        raise NativeTabError(_engine_message(exc)) from exc
    return {
        "node_count": report.node_count,
        "filled_node_count": len(report.fills),
        "pressure_points": len(request["pressures"]),
        "temperature_points": len(request["temperatures"]),
        "fill_report": report.sidecar_path,
        "elapsed_s": round(report.elapsed_s, 3),
    }
