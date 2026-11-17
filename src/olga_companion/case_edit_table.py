"""The values a user may change by hand in one workspace .genkey, read from the case itself.

Each row maps to one operation of the closed edit grammar, so a hand edit goes through the same
reviewed transaction as an assistant edit. A case the app compiled (it carries the CaseSpec marker)
offers every typed value; any other GENKEY offers only its INTEGRATION ENDTIME, the one edit the
owner-byte path supports.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from . import case_transactions
from .case_spec_recovery import UnsupportedSourceError, recover_case_spec
from .case_spec import CaseSpec


def _row(row_id: str, target: str, field: str, value: float, unit: str, op: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"id": row_id, "target": target, "field": field, "value": value, "unit": unit, "op": op}
    if note:
        row["note"] = note
    return row


def _spec_rows(spec: CaseSpec) -> list[dict[str, Any]]:
    rows = [_row("integration.end_time_s", "ENDTIME", "end_time_s", spec.integration.end_time_s, "s", {"op": "set_integration"})]
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
    for path in spec.flowpaths:
        for pipe in path.pipes:
            rows.append(_row(f"flowpaths.{path.label}.pipes.{pipe.label}.roughness_m", f"{path.label}/{pipe.label}",
                             "roughness_m", pipe.roughness_m, "m",
                             {"op": "set_pipe_roughness", "flowpath": path.label, "pipe": pipe.label}))
    return rows


def _owner_rows(text: str) -> list[dict[str, Any]]:
    matches = case_transactions._endtime_matches(text)
    if len(matches) != 1:
        return []
    unit = matches[0].group("unit")
    if unit is not None and unit.casefold() not in case_transactions._SECOND_UNITS:
        return []
    try:
        value = float(matches[0].group("number"))
    except ValueError:
        return []
    if not math.isfinite(value):
        return []
    return [_row("integration.end_time_s", "ENDTIME", "end_time_s", value, "s", {"op": "set_integration"})]


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
        return {"source_hash": source_hash, "marked": False, "rows": _owner_rows(text)}
    return {"source_hash": source_hash, "marked": True, "rows": _spec_rows(spec)}


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
