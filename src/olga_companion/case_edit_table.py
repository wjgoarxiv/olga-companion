"""The values a user may change by hand in one workspace .genkey, read from the case itself.

Each row maps to one operation of the closed edit grammar, so a hand edit goes through the same
reviewed transaction as an assistant edit. A case the app compiled (it carries the CaseSpec marker)
offers every typed value; any other GENKEY offers its INTEGRATION ENDTIME and the length of each
pipe, the edits the owner-byte path supports.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from . import case_transactions
from .case_compiler import derived_output_intervals
from .case_lint import table_path
from .case_spec_types import DEFAULT_DTSTART_S, DEFAULT_MINDT_S
from .case_spec_recovery import UnsupportedSourceError, recover_case_spec
from .case_spec import CaseSpec
from .owner_pipe_length import owner_pipe_lengths


def _row(row_id: str, target: str, field: str, value: float | None, unit: str, op: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"id": row_id, "target": target, "field": field, "value": value, "unit": unit, "op": op}
    if note:
        row["note"] = note
    return row


_TIMING: tuple[tuple[str, str], ...] = (
    ("max_dt_s", "MAXDT"), ("min_dt_s", "MINDT"), ("dt_start_s", "DTSTART"),
    ("trend_interval_s", "TREND DTPLOT"), ("profile_interval_s", "PROFILE DTPLOT"), ("output_interval_s", "OUTPUT DTOUT"),
)


def _timing_rows(integration: Any) -> list[dict[str, Any]]:
    """The time step and output intervals. A value the case leaves out shows what the compiler
    writes: the intervals follow the end time (note "derived"), MINDT and DTSTART are the
    compiler's fixed defaults (note "default"); MAXDT, which it never invents, shows blank
    (note "unset").
    Typing a value states it."""
    trend, profile, output = derived_output_intervals(integration.end_time_s)
    defaults = {"max_dt_s": None, "min_dt_s": DEFAULT_MINDT_S, "dt_start_s": DEFAULT_DTSTART_S,
                "trend_interval_s": trend, "profile_interval_s": profile, "output_interval_s": output}
    rows = []
    for field, target in _TIMING:
        stated = getattr(integration, field)
        value = stated if stated is not None else defaults[field]
        if stated is not None:
            note = None
        elif value is None:
            note = "unset"
        else:
            note = "default" if field in ("min_dt_s", "dt_start_s") else "derived"
        rows.append(_row(f"integration.{field}", target, field, value, "s", {"op": "set_time_step"}, note))
    return rows


_THERMAL_TARGETS: tuple[tuple[str, str], ...] = (
    ("ambient_temperature_c", "TAMBIENT"), ("outer_heat_transfer_coefficient_w_m2k", "HAMBIENT"),
    ("wall_thickness_m", "WALL"), ("wall_conductivity_w_mk", "MATERIAL"),
    ("wall_heat_capacity_j_kgk", "MATERIAL"), ("wall_density_kg_m3", "MATERIAL"),
)


def _thermal_rows(thermal: Any) -> list[dict[str, Any]]:
    """The ambient heat-transfer values; an adiabatic case has none to change."""
    if getattr(thermal, "model", None) != "ambient_h_given":
        return []
    material = thermal.wall.material
    values = {
        "ambient_temperature_c": thermal.ambient_temperature_c,
        "outer_heat_transfer_coefficient_w_m2k": thermal.outer_heat_transfer_coefficient_w_m2k,
        "wall_thickness_m": thermal.wall.thickness_m,
        "wall_conductivity_w_mk": material.conductivity_w_mk,
        "wall_heat_capacity_j_kgk": material.heat_capacity_j_kgk,
        "wall_density_kg_m3": material.density_kg_m3,
    }
    units = {"ambient_temperature_c": "C", "outer_heat_transfer_coefficient_w_m2k": "W/m2-K", "wall_thickness_m": "m",
             "wall_conductivity_w_mk": "W/m-K", "wall_heat_capacity_j_kgk": "J/kg-K", "wall_density_kg_m3": "kg/m3"}
    return [_row(f"thermal.{field}", target, field, values[field], units[field], {"op": "set_thermal_value"})
            for field, target in _THERMAL_TARGETS]


def _spec_rows(spec: CaseSpec) -> list[dict[str, Any]]:
    rows = [_row("integration.end_time_s", "ENDTIME", "end_time_s", spec.integration.end_time_s, "s", {"op": "set_integration"})]
    rows.extend(_timing_rows(spec.integration))
    rows.extend(_thermal_rows(spec.thermal))
    for node in spec.nodes:
        if node.kind not in ("source", "sink"):
            continue
        rows.append(_row(f"nodes.{node.label}.pressure_pa", node.label, "pressure_pa", node.pressure_pa, "Pa",
                         {"op": "set_boundary_pressure", "node": node.label}))
        rows.append(_row(f"nodes.{node.label}.temperature_c", node.label, "temperature_c", node.temperature_c, "C",
                         {"op": "set_boundary_temperature", "node": node.label}))
    for source in spec.massflow_sources:
        rows.append(_row(f"massflow_sources.{source.label}.mass_flow_kg_s", source.label, "mass_flow_kg_s",
                         source.mass_flow_kg_s, "kg/s", {"op": "set_source_massflow", "label": source.label},
                         "series" if source.series else None))
    for item in spec.equipment:
        if getattr(item, "kind", None) != "valve":
            continue
        rows.append(_row(f"equipment.{item.label}.opening", item.label, "opening", item.opening, "fraction",
                         {"op": "set_valve_opening", "label": item.label},
                         "schedule" if item.schedule else None))
    for loop in spec.controllers:
        setpoint_unit = "Pa" if loop.measure.variable == "PT" else "kg/s"
        for field, unit in (("setpoint", setpoint_unit), ("gain", ""), ("integral_s", "s"), ("derivative_s", "s")):
            rows.append(_row(f"controllers.{loop.label}.{field}", loop.label, field, getattr(loop, field), unit,
                             {"op": "set_controller_value", "label": loop.label}))
    for path in spec.flowpaths:
        for pipe in path.pipes:
            rows.append(_row(f"flowpaths.{path.label}.pipes.{pipe.label}.roughness_m", f"{path.label}/{pipe.label}",
                             "roughness_m", pipe.roughness_m, "m",
                             {"op": "set_pipe_roughness", "flowpath": path.label, "pipe": pipe.label}))
            rows.append(_row(f"flowpaths.{path.label}.pipes.{pipe.label}.diameter_m", f"{path.label}/{pipe.label}",
                             "diameter_m", pipe.diameter_m, "m",
                             {"op": "set_pipe_geometry", "flowpath": path.label, "pipe": pipe.label}))
            rows.append(_length_row(path.label, pipe.label, pipe.length))
    return rows


def _length_row(flowpath: str, pipe: str, length_m: float) -> dict[str, Any]:
    return _row(f"flowpaths.{flowpath}.pipes.{pipe}.length_m", f"{flowpath}/{pipe}", "length_m", length_m, "m",
                {"op": "set_pipe_length", "flowpath": flowpath, "pipe": pipe})


def _owner_rows(text: str) -> list[dict[str, Any]]:
    lengths = [_length_row(flowpath, pipe, length) for flowpath, pipe, length in owner_pipe_lengths(text)]
    matches = case_transactions._endtime_matches(text)
    if len(matches) != 1:
        return lengths
    unit = matches[0].group("unit")
    if unit is not None and unit.casefold() not in case_transactions._SECOND_UNITS:
        return lengths
    try:
        value = float(matches[0].group("number"))
    except ValueError:
        return lengths
    if not math.isfinite(value):
        return lengths
    return [_row("integration.end_time_s", "ENDTIME", "end_time_s", value, "s", {"op": "set_integration"}), *lengths]


def _with_keywords(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each row names the OLGA KEYWORD.KEY it changes, from the same map the keyword coverage uses."""
    return [{**row, "keyword": keyword} if (keyword := table_path(row)) else row for row in rows]


def editable_rows(source: Path) -> dict[str, Any]:
    """Rows, the exact source hash they were read from, and whether the full grammar applies."""
    content = source.read_bytes()
    source_hash = hashlib.sha256(content).hexdigest()
    try:
        spec = recover_case_spec(source)
    except UnsupportedSourceError as exc:
        if exc.reason != "provenance marker is absent":
            # Made by the app and changed by hand since: the planner refuses every edit, so offer none.
            return {"source_hash": source_hash, "marked": False, "rows": [], "reason": "not_exact_compile"}
        try:
            text = content.decode("utf-8")
        except UnicodeError:
            return {"source_hash": source_hash, "marked": False, "rows": []}
        return {"source_hash": source_hash, "marked": False, "rows": _with_keywords(_owner_rows(text))}
    return {"source_hash": source_hash, "marked": True, "rows": _with_keywords(_spec_rows(spec))}


def _base(source: Path) -> str:
    stem = source.stem
    return stem.rsplit(".edit", 1)[0] if ".edit" in stem and stem.rsplit(".edit", 1)[1].isdigit() else stem


def is_edited_copy(source: Path, destination: Path) -> bool:
    """True when the destination is an edited-copy name beside the source, as `edited_name` gives."""
    pattern = rf"{re.escape(_base(source))}\.edit\d{{1,3}}\.genkey"
    return destination.parent == source.parent and re.fullmatch(pattern, destination.name) is not None


def edited_name(source: Path) -> str:
    """The first free `<stem>.edit<N>.genkey` beside the source; the source itself is never replaced."""
    base = _base(source)
    for index in range(1, 1000):
        candidate = source.with_name(f"{base}.edit{index}.genkey")
        if not candidate.exists():
            return candidate.name
    raise FileExistsError("No free edited-copy name is left beside this case.")
