"""Turn the rows of a pipe table into a CaseSpec v3 network.

Pipe rows (one per pipe, in flow order) name their flowpath and its from/to nodes; node
rows give boundary values. Junctions are every node that joins two or more flowpaths.
Labels are generated in table order and `label_map` keeps the table's own names.
Nothing here writes a file and no missing geometry or boundary value is guessed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .case_spec import V3_MAX_SOURCES, V3_MAX_TOTAL_SECTIONS, V3_MAX_VALVES, normalize_case_spec
from .case_spec_validation import validation_issue
from .pipe_table import READER_ISSUE_CODES, PipeTable
from .segmentation import PipeRun, junction_ratio_warnings, segment_flowpath

MAX_NODES = 256
MAX_FLOWPATHS = 512
MAX_PIPES_PER_FLOWPATH = 500
MAX_VALVES = V3_MAX_VALVES
MAX_SECTIONS = V3_MAX_TOTAL_SECTIONS
START_PRESSURE_RATIO = 1.5
_COORD_END = ("x_m", "y_m", "z_m")
_COORD_START = ("x_start_m", "y_start_m", "z_start_m")
_MIX_REASON = "do not mix coordinate rows (x_m, y_m, z_m) with length_m/elevation_m rows in one table"
_BOUNDARY_FIELDS = ("pressure_pa", "temperature_c", "gas_fraction", "water_fraction")
_KINDS = {"source": "source", "inlet": "source", "sink": "sink", "outlet": "sink", "closed": "closed"}
_SCHEDULE_POINT = re.compile(r"^\s*([0-9.eE+-]+)\s*[:=]\s*([0-9.eE+-]+)\s*$")
_DECIMALS = 9
_MAX_DIAMETER_M = 10.0
_MAX_ROUGHNESS_M = 0.1
_MAX_METRES = 10_000_000.0


@dataclass(frozen=True)
class ImportOptions:
    pvt_reference: str
    fluid_label: str
    thermal: Mapping[str, Any]
    end_time_s: float
    max_section_m: float = 1.0
    max_ratio: float = 2.0
    outputs: tuple[str, ...] = ("HOL", "PT", "TM")
    max_dt_s: float | None = None
    initial_pressure_pa: float | None = None
    initial_temperature_c: float | None = None


@dataclass(frozen=True)
class ImportIssue:
    row: int | None
    field: str
    reason: str
    code: str = ""
    params: dict[str, object] = field(default_factory=dict)


# Stable codes for every issue the importer can raise, in the order the checks
# run. The frontend renders `pipeDraft.reason.<code>` with `params` and keeps
# the English `reason` for the model. Reader codes come first so a carried
# reader issue keeps the code the reader gave it; validation refusals use
# `spec.<code>` with the code the CaseSpec check reported.
ISSUE_CODES: tuple[str, ...] = (
    *READER_ISSUE_CODES,
    "coord_start_mismatch",
    "coord_start_missing",
    "coord_later_start_mismatch",
    "coord_length_not_finite",
    "coord_zero_length",
    "coord_end_mismatch",
    "mixed_coord_length",
    "coord_end_not_numbers",
    "coord_end_not_finite",
    "coord_start_not_numbers",
    "coord_start_not_finite",
    "duplicate_boundary_row",
    "missing_flowpath",
    "flowpath_nodes_disagree",
    "flowpath_nodes_missing",
    "value_missing",
    "value_not_finite",
    "value_not_positive",
    "roughness_negative",
    "diameter_over_limit",
    "roughness_over_limit",
    "elevation_over_length",
    "no_pipe_rows",
    "bad_max_section",
    "bad_max_ratio",
    "section_estimate_over_caps",
    "bad_node_kind",
    "closed_bad_degree",
    "closed_bad_mass_flow",
    "boundary_missing",
    "boundary_temperature_range",
    "boundary_fraction_range",
    "boundary_bad_degree",
    "junction_bad_degree",
    "missing_boundary_row",
    "disconnected_topology",
    "missing_inlet_sink",
    "table_over_caps",
    "valve_schedule_missing",
    "valve_schedule_bad_format",
    "valve_position_range",
    "sections_over_caps",
    "initial_void_fraction_out_of_range",
    "initial_void_fraction_disagrees",
)


@dataclass(frozen=True)
class ImportResult:
    spec: dict[str, Any] | None
    issues: tuple[ImportIssue, ...]
    summary: dict[str, Any] = field(default_factory=dict)
    label_map: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class _Flowpath:
    name: str
    start: str
    end: str
    rows: list[tuple[int | None, dict[str, object]]]


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _schedule(text: str) -> tuple[list[tuple[float, float]] | None, str | None, str]:
    """Parse a valve schedule, or return the problem and its code."""
    if not text:
        return None, "state the valve opening (0-1) or a schedule like 0:1, 299:1, 300:0", "valve_schedule_missing"
    try:
        return [(0.0, float(text))], None, ""
    except ValueError:
        pass
    points = []
    for part in text.split(","):
        matched = _SCHEDULE_POINT.match(part)
        try:
            if matched is None:
                raise ValueError(part)
            points.append((float(matched[1]), float(matched[2])))
        except ValueError:
            return None, "write the schedule as time:opening pairs, for example 0:1, 299:1, 300:0", "valve_schedule_bad_format"
    return points, None, ""


def _rounded(cells: Sequence[float], length: float) -> list[float]:
    """Round section lengths and put the remainder on the last so they sum to the length."""
    values = [round(cell, _DECIMALS) for cell in cells[:-1]]
    values.append(round(length - math.fsum(values), _DECIMALS))
    return values


_NODE_TOL_M = 0.001
_MAX_MASS_FLOW_KG_S = 1_000_000.0
# Table-derived names in prose: cut to the source_name width and quoted, so a
# hostile or clumsy table cannot flood an issue reason or the tool overview.
_MAX_NAME_DISPLAY = 48


def _quoted(text: object) -> str:
    return f"'{str(text)[:_MAX_NAME_DISPLAY]}'"


def _in_range(value: object, low: float, high: float, low_open: bool = False) -> bool:
    """Finite number within bounds (same edges as the CaseSpec field that takes it)."""
    return (
        isinstance(value, float) and math.isfinite(value)
        and (low < value if low_open else low <= value) and value <= high
    )


def _boundary_problem(key: str, value: object, word: str) -> tuple[str | None, str]:
    """Name the row's problem with a boundary value, or None when it is usable.

    Returns (problem, code); the code is empty when the value is usable.
    """
    if not isinstance(value, float):
        return f"{key} is missing for this {word}", "boundary_missing"
    if key == "temperature_c":
        if not _in_range(value, -273.15, 1_500.0, low_open=True):
            return f"temperature_c is outside -273.15..1500 C for this {word}", "boundary_temperature_range"
    elif key in ("gas_fraction", "water_fraction"):
        if not _in_range(value, 0.0, 1.0):
            return f"{key} is outside 0..1 for this {word}", "boundary_fraction_range"
    return None, ""


def _coord_style(row: dict[str, object]) -> tuple[str, tuple[str, str, str] | None]:
    """Classify a pipe row and check its row-local coordinate fields.

    Returns (style, problem): style is "length", "coord" or "mixed"; problem is
    a (field, reason, code) triple when the row is refused. Lengths are derived
    later in flowpath order, once upstream node positions are known.
    """
    has_plain = row.get("length_m") is not None or row.get("elevation_m") is not None
    has_coord = any(row.get(key) is not None for key in _COORD_END)
    if has_plain and has_coord:
        return "mixed", ("x_m", _MIX_REASON, "mixed_coord_length")
    if not has_coord:
        return "length", None
    end = [row.get(key) for key in _COORD_END]
    if any(not isinstance(value, float) for value in end):
        return "coord", ("x_m", "give x_m, y_m and z_m together as numbers", "coord_end_not_numbers")
    if any(not math.isfinite(value) or abs(value) > _MAX_METRES for value in end):
        return "coord", ("x_m", "value is not a finite length up to 10,000 km", "coord_end_not_finite")
    stated = [row.get(key) for key in _COORD_START]
    if any(value is not None for value in stated):
        if any(not isinstance(value, float) for value in stated):
            return "coord", ("x_start_m", "give x_start_m, y_start_m and z_start_m together as numbers", "coord_start_not_numbers")
        if any(not math.isfinite(value) or abs(value) > _MAX_METRES for value in stated):
            return "coord", ("x_start_m", "value is not a finite length up to 10,000 km", "coord_start_not_finite")
    return "coord", None


def _upstream_first(flowpaths: dict[str, _Flowpath]) -> list[str]:
    """Order flowpaths so each starts where an upstream end already is.

    Kahn's pass over the from/to graph in table order; a directed cycle keeps
    table order for its members. Predecessors are indexed by node, so the pass
    is linear in flowpaths plus junctions.
    """
    names = list(flowpaths)
    by_end: dict[str, list[str]] = {}
    for name in names:
        by_end.setdefault(flowpaths[name].end, []).append(name)
    predecessors = {
        name: {other for other in by_end.get(flowpaths[name].start, ()) if other != name}
        for name in names
    }
    successors: dict[str, list[str]] = {name: [] for name in names}
    for name in names:
        for other in predecessors[name]:
            successors[other].append(name)
    order: list[str] = []
    ready = [name for name in names if not predecessors[name]]
    queued, done = set(ready), set()
    cursor = 0
    while cursor < len(ready):
        name = ready[cursor]
        cursor += 1
        order.append(name)
        done.add(name)
        for other in successors[name]:
            predecessors[other].discard(name)
            if not predecessors[other] and other not in done and other not in queued:
                ready.append(other)
                queued.add(other)
    order.extend(name for name in names if name not in done)
    return order


def _at(node: str, point: tuple[float, float, float]) -> str:
    return f"{_quoted(node)} at ({point[0]:g}, {point[1]:g}, {point[2]:g}) m"


def _resolve_flowpath(
    item: _Flowpath,
    node_pos: dict[str, tuple[float, float, float]],
    taken: dict[str, bool],
    allow_origin: bool,
    issues: list[ImportIssue],
) -> None:
    """Derive length_m/elevation_m for one flowpath's coordinate rows.

    A flowpath starts at its first row's start columns, at the position an
    already-converted flowpath left at its from_node, or — only when no row
    states a start, for the network's first such inlet — at the origin. A node
    claimed twice more than 1 mm apart is an issue naming the row.
    """
    first_line, first_row = item.rows[0]
    stated = tuple(first_row.get(key) for key in _COORD_START)
    if any(value is not None for value in stated):
        start = tuple(float(value) for value in stated)
        if item.start in node_pos and math.dist(start, node_pos[item.start]) > _NODE_TOL_M:
            issues.append(ImportIssue(
                first_line, "x_start_m",
                f"{_at(item.start, node_pos[item.start])} in another flowpath; "
                "this start is more than 1 mm away",
                "coord_start_mismatch", {"node": item.start[:_MAX_NAME_DISPLAY]}))
            return
        node_pos.setdefault(item.start, start)
    elif item.start in node_pos:
        start = node_pos[item.start]
    elif allow_origin and not taken["origin"]:
        start = (0.0, 0.0, 0.0)
        taken["origin"] = True
        node_pos[item.start] = start
    else:
        issues.append(ImportIssue(
            first_line, "x_start_m",
            f"state x_start_m, y_start_m and z_start_m for the start of {_quoted(item.start)}; "
            "the origin is only assumed when no flowpath states a start",
            "coord_start_missing", {"node": item.start[:_MAX_NAME_DISPLAY]}))
        return
    for index, (line, row) in enumerate(item.rows):
        if index > 0:
            restated = [row.get(key) for key in _COORD_START]
            if any(value is not None for value in restated):
                if math.dist(tuple(float(value) for value in restated), start) > _NODE_TOL_M:
                    issues.append(ImportIssue(
                        line, "x_start_m",
                        "x_start_m, y_start_m and z_start_m on later rows must "
                        "match the previous end within 1 mm",
                        "coord_later_start_mismatch", {}))
                    return
        end = tuple(float(row[key]) for key in _COORD_END)
        length = math.dist(start, end)
        elevation = end[1] - start[1]
        if not math.isfinite(length) or length > _MAX_METRES:
            issues.append(ImportIssue(line, "length_m", "value is not a finite length up to 10,000 km", "coord_length_not_finite", {}))
            return
        if length <= 0:
            issues.append(ImportIssue(
                line, "length_m",
                "a coordinate pipe has zero length: it ends where it starts (x_m, y_m, z_m)",
                "coord_zero_length", {}))
            return
        row["length_m"], row["elevation_m"] = length, elevation
        start = end
    if item.end in node_pos and math.dist(start, node_pos[item.end]) > _NODE_TOL_M:
        issues.append(ImportIssue(
            item.rows[-1][0], "x_m",
            f"{_at(item.end, node_pos[item.end])} in another flowpath; "
            "this row ends more than 1 mm away",
            "coord_end_mismatch", {"node": item.end[:_MAX_NAME_DISPLAY]}))
    else:
        node_pos[item.end] = start


def _resolve_coordinates(flowpaths: dict[str, _Flowpath], issues: list[ImportIssue]) -> bool:
    """Fill length_m/elevation_m for every coordinate-style flowpath, upstream first.

    Returns True when the origin stood in for a missing start. The origin is
    only available when no inlet anchors itself: a start stated mid-network
    (a later row, or a flowpath with an incoming flowpath) only checks
    consistency, it does not fix the absolute frame.
    """
    by_end: dict[str, list[_Flowpath]] = {}
    for other in flowpaths.values():
        by_end.setdefault(other.end, []).append(other)
    anchored = False
    for item in flowpaths.values():
        first_start = [item.rows[0][1].get(key) for key in _COORD_START]
        if all(value is not None for value in first_start) and not any(
            other is not item for other in by_end.get(item.start, ())
        ):
            anchored = True
            break
    allow_origin = not anchored
    node_pos: dict[str, tuple[float, float, float]] = {}
    taken = {"origin": False}
    for name in _upstream_first(flowpaths):
        item = flowpaths[name]
        if all(row.get("x_m") is None for _, row in item.rows):
            continue
        _resolve_flowpath(item, node_pos, taken, allow_origin, issues)
    return taken["origin"]


def build_case_spec(table: PipeTable, options: ImportOptions) -> ImportResult:
    """Return a validated v3 spec, or issues naming the table rows that block it."""
    issues: list[ImportIssue] = list(
        ImportIssue(issue.row, issue.column, issue.reason, issue.code, dict(issue.params))
        for issue in table.issues
    )
    lines = table.lines or tuple(range(1, len(table.rows) + 1))
    flowpaths: dict[str, _Flowpath] = {}
    boundaries: dict[str, tuple[int | None, dict[str, object]]] = {}
    styles: list[tuple[int | None, str]] = []
    work = [dict(row) for row in table.rows]
    for line, row in zip(lines, work):
        name = _text(row, "flowpath")
        if not name and _text(row, "node"):
            node = _text(row, "node")
            if node in boundaries:
                first_line = boundaries[node][0]
                issues.append(ImportIssue(
                    line, "node",
                    f"duplicate boundary row for {_quoted(node)}; the first is on row {first_line}",
                    "duplicate_boundary_row",
                    {"node": node[:_MAX_NAME_DISPLAY], "first_row": first_line},
                ))
            else:
                boundaries[node] = (line, row)
            continue
        if not name:
            issues.append(ImportIssue(line, "flowpath", "a pipe row needs its flowpath name", "missing_flowpath", {}))
            continue
        start, end = _text(row, "from_node"), _text(row, "to_node")
        current = flowpaths.setdefault(name, _Flowpath(name, start, end, []))
        if (start, end) != (current.start, current.end):
            issues.append(ImportIssue(line, "to_node", f"{_quoted(name)} rows disagree on their from/to nodes", "flowpath_nodes_disagree", {"flowpath": name[:_MAX_NAME_DISPLAY]}))
        if not start or not end:
            issues.append(ImportIssue(line, "from_node", f"{_quoted(name)} needs from_node and to_node", "flowpath_nodes_missing", {"flowpath": name[:_MAX_NAME_DISPLAY]}))
        current.rows.append((line, row))
        for key in ("inner_diameter_m", "roughness_m"):
            value = row.get(key)
            if not isinstance(value, float):
                issues.append(ImportIssue(line, key, "value is missing", "value_missing", {"field": key}))
            elif not math.isfinite(value) or abs(value) > _MAX_METRES:
                issues.append(ImportIssue(line, key, "value is not a finite length up to 10,000 km", "value_not_finite", {"field": key}))
            elif key == "inner_diameter_m" and value <= 0:
                issues.append(ImportIssue(line, key, "value must be greater than zero", "value_not_positive", {"field": key}))
            elif key == "roughness_m" and value < 0:
                issues.append(ImportIssue(line, key, "roughness cannot be negative", "roughness_negative", {}))
            elif key == "inner_diameter_m" and value > _MAX_DIAMETER_M:
                issues.append(ImportIssue(line, key, "diameter over 10 m; is the column in mm? state the unit in the header", "diameter_over_limit", {"limit_m": _MAX_DIAMETER_M}))
            elif key == "roughness_m" and value > _MAX_ROUGHNESS_M:
                issues.append(ImportIssue(line, key, "roughness over 0.1 m; is the column in mm? state the unit in the header", "roughness_over_limit", {"limit_m": _MAX_ROUGHNESS_M}))
        style, problem = _coord_style(row)
        if problem is not None:
            field, reason, code = problem
            issues.append(ImportIssue(line, field, reason, code, {}))
        else:
            if style == "length":
                for key in ("length_m", "elevation_m"):
                    value = row.get(key)
                    if not isinstance(value, float):
                        issues.append(ImportIssue(line, key, "value is missing", "value_missing", {"field": key}))
                    elif not math.isfinite(value) or abs(value) > _MAX_METRES:
                        issues.append(ImportIssue(line, key, "value is not a finite length up to 10,000 km", "value_not_finite", {"field": key}))
                    elif key == "length_m" and value <= 0:
                        issues.append(ImportIssue(line, key, "value must be greater than zero", "value_not_positive", {"field": key}))
            styles.append((line, style))
        length, elevation = row.get("length_m"), row.get("elevation_m")
        if isinstance(length, float) and isinstance(elevation, float) and length > 0 and abs(elevation) > length:
            issues.append(ImportIssue(line, "elevation_m", "a pipe cannot rise or fall more than its length; check the units", "elevation_over_length", {}))
        start_void = row.get("initial_void_fraction")
        if start_void is not None and not (isinstance(start_void, float) and 0.0 <= start_void <= 1.0):
            issues.append(ImportIssue(line, "initial_void_fraction", "initial_void_fraction must be a fraction from 0 to 1", "initial_void_fraction_out_of_range", {}))
    pure = [(line, style) for line, style in styles if style in ("length", "coord")]
    if {style for _, style in pure} == {"length", "coord"}:
        first = next(style for _, style in pure)
        for line, style in pure:
            if style != first:
                issues.append(ImportIssue(
                    line, "x_m" if style == "coord" else "length_m", _MIX_REASON,
                    "mixed_coord_length", {}))
    if not flowpaths and not issues:
        issues.append(ImportIssue(None, "flowpath", "the table has no pipe rows", "no_pipe_rows", {}))
    if not math.isfinite(options.max_section_m) or options.max_section_m <= 0:
        issues.append(ImportIssue(None, "max_section_m", "max_section_m must be a positive length", "bad_max_section", {}))
    if not math.isfinite(options.max_ratio) or options.max_ratio <= 1:
        issues.append(ImportIssue(None, "max_ratio", "max_ratio must be a length ratio greater than 1", "bad_max_ratio", {}))
    origin_assumed = False
    if not issues and any(style == "coord" for _, style in styles):
        origin_assumed = _resolve_coordinates(flowpaths, issues)
    if not issues:
        estimate = sum(
            max(2, math.ceil(float(row["length_m"]) / options.max_section_m))
            for item in flowpaths.values() for _line, row in item.rows
        )
        if estimate > MAX_SECTIONS:
            issues.append(ImportIssue(
                None, "caps", f"the table is larger than a case can hold: about {estimate} sections > "
                f"{MAX_SECTIONS}; use a larger max_section_m",
                "section_estimate_over_caps",
                {"sections": estimate, "limit": MAX_SECTIONS},
            ))
    if issues:
        return ImportResult(None, tuple(issues))

    incoming: dict[str, list[str]] = {}
    outgoing: dict[str, list[str]] = {}
    for item in flowpaths.values():
        outgoing.setdefault(item.start, []).append(item.name)
        incoming.setdefault(item.end, []).append(item.name)
    node_names = list(dict.fromkeys(name for item in flowpaths.values() for name in (item.start, item.end)))
    kinds: dict[str, str] = {}
    for name in node_names:
        degree = (len(incoming.get(name, [])), len(outgoing.get(name, [])))
        if name in boundaries:
            line, row = boundaries[name]
            kind = _KINDS.get(_text(row, "node_kind").lower())
            if kind is None:
                issues.append(ImportIssue(line, "node_kind", f"{_quoted(name)}: node_kind must be source, sink or closed", "bad_node_kind", {"node": name[:_MAX_NAME_DISPLAY]}))
                continue
            if kind == "closed":
                if degree != (0, 1):
                    issues.append(ImportIssue(
                        line, name,
                        f"a closed end must sit at a flowpath inlet; {_quoted(name)} has "
                        f"{degree[0]} incoming and {degree[1]} outgoing flowpath",
                        "closed_bad_degree",
                        {"node": name[:_MAX_NAME_DISPLAY], "incoming": degree[0], "outgoing": degree[1]}))
                    continue
                flow = row.get("mass_flow_kg_s")
                if not _in_range(flow, 0.0, _MAX_MASS_FLOW_KG_S, low_open=True):
                    issues.append(ImportIssue(
                        line, name,
                        "a closed inlet needs mass_flow_kg_s greater than zero "
                        "and at most 1e6 kg/s",
                        "closed_bad_mass_flow", {"node": name[:_MAX_NAME_DISPLAY]}))
                    continue
                for key in ("temperature_c", "gas_fraction", "water_fraction"):
                    problem, code = _boundary_problem(key, row.get(key), "closed inlet")
                    if problem is not None:
                        issues.append(ImportIssue(line, name, problem, code, {"node": name[:_MAX_NAME_DISPLAY], "key": key}))
                kinds[name] = kind
                continue
            expected = (0, 1) if kind == "source" else (1, 0)
            if degree != expected:
                issues.append(ImportIssue(line, name, f"a {kind} needs {expected[1]} outgoing and {expected[0]} incoming flowpath", "boundary_bad_degree", {"node": name[:_MAX_NAME_DISPLAY], "kind": kind, "incoming": degree[0], "outgoing": degree[1]}))
            for key in _BOUNDARY_FIELDS:
                problem, code = _boundary_problem(key, row.get(key), "boundary")
                if problem is not None:
                    issues.append(ImportIssue(line, name, problem, code, {"node": name[:_MAX_NAME_DISPLAY], "key": key}))
            kinds[name] = kind
        elif sum(degree) >= 2:
            if min(degree) != 1 or sum(degree) > 7:
                issues.append(ImportIssue(
                    None, name,
                    f"a junction needs exactly one flowpath on one side and 2-7 in all; it has {degree[0]} in and {degree[1]} out",
                    "junction_bad_degree",
                    {"node": name[:_MAX_NAME_DISPLAY], "incoming": degree[0], "outgoing": degree[1]},
                ))
            kinds[name] = "junction"
        else:
            issues.append(ImportIssue(None, name, "this end node needs a boundary row (source, sink or closed)", "missing_boundary_row", {"node": name[:_MAX_NAME_DISPLAY]}))
    if not _connected(node_names, flowpaths.values()):
        issues.append(ImportIssue(None, "topology", "the flowpaths do not form one connected network", "disconnected_topology", {}))
    if "sink" not in kinds.values() or not ({"source", "closed"} & set(kinds.values())):
        issues.append(ImportIssue(
            None, "topology", "the network needs an inlet (a source or a closed end) and a sink node row",
            "missing_inlet_sink", {}))

    valve_rows = [
        (line, row, item) for item in flowpaths.values() for line, row in item.rows if _text(row, "valve")
    ]
    caps = [
        f"{label} {count} > {limit}"
        for label, count, limit in (
            ("nodes", len(node_names), MAX_NODES),
            ("flowpaths", len(flowpaths), MAX_FLOWPATHS),
            ("pipes in one flowpath", max(len(item.rows) for item in flowpaths.values()), MAX_PIPES_PER_FLOWPATH),
            ("valves", len(valve_rows), MAX_VALVES),
            ("boundaries", sum(1 for kind in kinds.values() if kind != "junction"), V3_MAX_SOURCES + MAX_NODES),
        )
        if count > limit
    ]
    if caps:
        issues.append(ImportIssue(None, "caps", "the table is larger than a case can hold: " + ", ".join(caps), "table_over_caps", {"caps": list(caps)}))
    schedules: dict[int | None, list[tuple[float, float]]] = {}
    for line, row, _item in valve_rows:
        points, problem, code = _schedule(_text(row, "valve_schedule"))
        if problem is not None:
            issues.append(ImportIssue(line, "valve_schedule", problem, code, {}))
        else:
            schedules[line] = points
        position = row.get("valve_position")
        if not isinstance(position, float) or not 0.0 <= position <= 1.0:
            issues.append(ImportIssue(line, "valve_position", "valve_position must be a fraction from 0 to 1", "valve_position_range", {}))
    if issues:
        return ImportResult(None, tuple(issues))
    joined = _join_pass_through(flowpaths, kinds, node_names)
    issues.extend(_start_void_conflicts(flowpaths))
    if issues:
        return ImportResult(None, tuple(issues))
    result = _assemble(flowpaths, boundaries, kinds, node_names, schedules, options, origin_assumed)
    if result.spec is not None:
        labels = result.label_map["flowpaths"]
        for removed, kept in joined.items():
            labels[removed] = labels[kept]
    return result


def _join_pass_through(
    flowpaths: dict[str, _Flowpath], kinds: dict[str, str], node_names: list[str]
) -> dict[str, str]:
    """Join the two flowpaths at every 1-in/1-out junction into one flowpath.

    OLGA 2022 diverges at such a JUNCTIONNODE (absurd temperatures in the next section at
    the first step), and a pipe run that only continues needs no node. Returns
    {removed flowpath name: flowpath it now belongs to}.
    """
    joined: dict[str, str] = {}
    while True:
        incoming: dict[str, list[str]] = {}
        outgoing: dict[str, list[str]] = {}
        for item in flowpaths.values():
            outgoing.setdefault(item.start, []).append(item.name)
            incoming.setdefault(item.end, []).append(item.name)
        node = next((
            name for name in node_names
            if kinds.get(name) == "junction" and len(incoming.get(name, [])) == 1
            and len(outgoing.get(name, [])) == 1 and incoming[name] != outgoing[name]
        ), None)
        if node is None:
            return joined
        first, second = flowpaths[incoming[node][0]], flowpaths.pop(outgoing[node][0])
        first.rows.extend(second.rows)
        first.end = second.end
        node_names.remove(node)
        del kinds[node]
        joined[second.name] = first.name
        for removed, kept in joined.items():
            if kept == second.name:
                joined[removed] = first.name


def _start_voids(item: _Flowpath) -> list[tuple[int | None, str, float]]:
    return [
        (line, _text(row, "flowpath"), float(row["initial_void_fraction"]))
        for line, row in item.rows if isinstance(row.get("initial_void_fraction"), float)
    ]


def _start_void_conflicts(flowpaths: dict[str, _Flowpath]) -> list[ImportIssue]:
    """One flowpath starts from one void fraction; a join must not mix two stated ones."""
    issues = []
    for item in flowpaths.values():
        stated = _start_voids(item)
        first = next(iter(stated), None)
        clash = next((entry for entry in stated if entry[2] != first[2]), None) if first else None
        if clash is not None:
            issues.append(ImportIssue(
                clash[0], "initial_void_fraction",
                f"{_quoted(first[1])} and {_quoted(clash[1])} form one flowpath but state different "
                "initial_void_fraction values; give them one value",
                "initial_void_fraction_disagrees",
                {"flowpath": first[1][:_MAX_NAME_DISPLAY], "joined": clash[1][:_MAX_NAME_DISPLAY]},
            ))
    return issues


def _connected(nodes: list[str], flowpaths) -> bool:
    adjacent: dict[str, set[str]] = {name: set() for name in nodes}
    for item in flowpaths:
        adjacent[item.start].add(item.end)
        adjacent[item.end].add(item.start)
    seen, pending = set(), [nodes[0]]
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(adjacent[name] - seen)
    return len(seen) == len(nodes)


def _assemble(
    flowpaths, boundaries, kinds, node_names, schedules, options: ImportOptions,
    origin_assumed: bool = False,
) -> ImportResult:
    prefixes = {"junction": "J", "source": "SRC", "sink": "SNK", "closed": "CLS"}
    counters: dict[str, int] = {}
    node_labels: dict[str, str] = {}
    for name in node_names:
        kind = kinds[name]
        counters[kind] = counters.get(kind, 0) + 1
        node_labels[name] = f"{prefixes[kind]}_{counters[kind]:03d}"
    nodes = []
    for name in node_names:
        node: dict[str, Any] = {"label": node_labels[name], "kind": kinds[name]}
        if kinds[name] in {"source", "sink"}:
            row = boundaries[name][1]
            node.update(
                pressure_pa=row["pressure_pa"], temperature_c=row["temperature_c"],
                gas_fraction=row["gas_fraction"], total_water_fraction=row["water_fraction"],
            )
        nodes.append(node)
    flowpath_labels: dict[str, str] = {}
    pipe_labels: dict[str, str] = {}
    valve_labels: dict[str, str] = {}
    pipes_seen: dict[str, int] = {}
    first_pipes: dict[str, str] = {}
    spec_flowpaths, equipment, ratio_rows = [], [], []
    worst, sections = 1.0, 0
    for number, item in enumerate(flowpaths.values(), start=1):
        label = f"FP_{number:03d}"
        flowpath_labels[item.name] = label
        runs = [
            PipeRun(float(row["length_m"]), (float(row.get("valve_position", 0.5)),) if _text(row, "valve") else ())
            for _line, row in item.rows
        ]
        # M2: a valved first pipe after a junction needs 3 sections, so the
        # junction-outlet shift (boundary 2 of at least 3) never yields 1.0.
        after_junction = kinds[item.start] == "junction"
        first_valved = bool(runs[0].valve_positions) and after_junction
        segmented = segment_flowpath(
            runs, options.max_section_m, max_ratio=options.max_ratio,
            refine_start=after_junction, refine_end=kinds[item.end] == "junction",
            first_min_sections=3 if first_valved else 0,
            min_first_valve_boundary=2 if after_junction else 1,
            outlet_valve_on_end=kinds[item.end] == "junction",
        )
        worst = max(worst, segmented.worst_ratio)
        pipes = []
        for index, ((line, row), cells, boundaries_k) in enumerate(
            zip(item.rows, segmented.lengths_m, segmented.valve_boundaries), start=1
        ):
            pipe_label = f"P_{number:03d}_{index:02d}"
            owner = _text(row, "flowpath")
            pipes_seen[owner] = pipes_seen.get(owner, 0) + 1
            pipe_labels[f"{owner}/{_text(row, 'pipe') or pipes_seen[owner]}"] = pipe_label
            if index == 1:
                first_pipes[item.name] = pipe_label
            length = float(row["length_m"])
            lengths = _rounded(cells, length)
            pipe: dict[str, Any] = {
                "label": pipe_label, "length_m": length, "elevation_m": float(row["elevation_m"]),
                "diameter_m": float(row["inner_diameter_m"]), "roughness_m": float(row["roughness_m"]),
                "sections": len(lengths),
            }
            if len(set(lengths)) > 1:
                pipe["segment_lengths_m"] = lengths
            pipes.append(pipe)
            sections += len(lengths)
            if _text(row, "valve"):
                valve_label = f"V_{len(equipment) + 1:03d}"
                valve_labels[_text(row, "valve")] = valve_label
                points = schedules[line]
                boundary = boundaries_k[0]
                if index == 1 and after_junction:
                    # OLGA refuses a valve on the first SECTIONBOUNDARY after a junction outlet.
                    boundary = max(boundary, 2)
                valve: dict[str, Any] = {
                    "kind": "valve", "label": valve_label, "flowpath": label, "pipe": pipe_label,
                    # The compiler places the valve at SECTIONBOUNDARY = int(position * sections).
                    # An outlet valve before another pipe takes the last boundary (position
                    # 1.0); every other boundary is below len(lengths), so its middle is used.
                    "position": 1.0 if boundary == len(lengths) else (boundary + 0.5) / len(lengths),
                    "diameter_m": float(row.get("valve_diameter_m") or row["inner_diameter_m"]),
                    "opening": points[0][1],
                }
                if len(points) > 1:
                    valve["schedule"] = [{"time_s": time, "opening": opening} for time, opening in points]
                equipment.append(valve)
        first, last = segmented.lengths_m[0][0], segmented.lengths_m[-1][-1]
        if kinds[item.start] == "junction":
            ratio_rows.append((node_labels[item.start], label, first))
        if kinds[item.end] == "junction":
            ratio_rows.append((node_labels[item.end], label, last))
        spec_flowpath: dict[str, Any] = {"label": label, "from": node_labels[item.start], "to": node_labels[item.end], "pipes": pipes}
        stated_voids = _start_voids(item)
        if stated_voids:
            spec_flowpath["initial_void_fraction"] = stated_voids[0][2]
        spec_flowpaths.append(spec_flowpath)
    # A closed inlet feeds a mass-flow source at section 1 of its flowpath's first pipe.
    # MS_ never collides: nodes take SRC_/SNK_/CLS_/J_, pipes P_, valves V_, and every
    # POSITION the compiler adds starts with POS_.
    sources = []
    for name in node_names:
        if kinds[name] != "closed":
            continue
        inlet = next(item for item in flowpaths.values() if item.start == name)
        row = boundaries[name][1]
        sources.append({
            "label": f"MS_{len(sources) + 1:03d}", "flowpath": flowpath_labels[inlet.name],
            "pipe": first_pipes[inlet.name], "section": 1, "time_s": 0.0,
            "mass_flow_kg_s": float(row["mass_flow_kg_s"]),
            "temperature_c": float(row["temperature_c"]),
            "gas_fraction": float(row["gas_fraction"]),
            "total_water_fraction": float(row["water_fraction"]),
        })
    # Centimetre sections need sub-millisecond steps; these are the values of a network deck
    # that reaches NORMAL STOP in OLGA 2022, not the 0.001 s / 1 s CaseSpec defaults.
    integration: dict[str, Any] = {"end_time_s": float(options.end_time_s), "min_dt_s": 1e-08, "dt_start_s": 1e-04}
    if options.max_dt_s is not None:
        integration["max_dt_s"] = float(options.max_dt_s)
    # OLGA's steady-state pre-processor did not converge on split/merge networks; the
    # network starts from a stated state, or the lowest boundary pressure filled with the
    # source fluid, instead.
    integration["steady_state"] = False
    boundary_nodes = [node for node in nodes if node["kind"] in {"source", "sink"}]
    # Closed inlets carry no pressure, but their stated fluid feeds the start state, so a
    # closed-only inlet still averages instead of dividing by zero.
    inlet_rows = [boundaries[name][1] for name in node_names if kinds[name] in {"source", "closed"}]
    pressures = [node["pressure_pa"] for node in boundary_nodes]
    initial = {
        "pressure_pa": min(pressures) if options.initial_pressure_pa is None else float(options.initial_pressure_pa),
        "temperature_c": (
            math.fsum(float(row["temperature_c"]) for row in inlet_rows) / len(inlet_rows)
            if options.initial_temperature_c is None else float(options.initial_temperature_c)
        ),
        "void_fraction": math.fsum(float(row["gas_fraction"]) for row in inlet_rows) / len(inlet_rows),
    }
    stated = options.initial_pressure_pa is not None or options.initial_temperature_c is not None
    # A guessed start far from the inlet pressure compresses or expands the fluid in the first
    # millisecond, out of the PVT table's temperature range (15 -> 6 bar aborted, 8 -> 6 ran).
    start_warning = None
    if not stated and max(pressures) > START_PRESSURE_RATIO * min(pressures):
        start_warning = {"highest_pressure_pa": max(pressures), "lowest_pressure_pa": min(pressures)}
    raw: dict[str, Any] = {
        "version": "3", "nodes": nodes, "flowpaths": spec_flowpaths,
        "pvt_reference": options.pvt_reference, "fluid_label": options.fluid_label,
        "thermal": dict(options.thermal), "integration": integration, "outputs": list(options.outputs),
        "initial_conditions": initial,
    }
    if equipment:
        raw["equipment"] = equipment
    if sources:
        raw["massflow_sources"] = sources
    label_map = {
        "nodes": node_labels, "flowpaths": flowpath_labels, "pipes": pipe_labels, "valves": valve_labels,
    }
    summary = {
        "flowpaths": len(spec_flowpaths), "pipes": sum(len(fp["pipes"]) for fp in spec_flowpaths),
        "junctions": sum(1 for kind in kinds.values() if kind == "junction"),
        "boundaries": sum(1 for kind in kinds.values() if kind != "junction"),
        "valves": len(equipment), "sections": sections,
        "shortest_section_m": min(c for fp in spec_flowpaths for p in fp["pipes"] for c in _cells(p)),
        "longest_section_m": max(c for fp in spec_flowpaths for p in fp["pipes"] for c in _cells(p)),
        "worst_ratio_in_flowpaths": round(worst, 3),
        "junction_ratio_warnings": junction_ratio_warnings(ratio_rows, options.max_ratio),
        "initial_state": {
            "pressure_pa": initial["pressure_pa"], "temperature_c": initial["temperature_c"], "stated": stated,
        },
        "start_warning": start_warning,
        "coordinate_origin_assumed": origin_assumed,
    }
    if sections > MAX_SECTIONS:
        return ImportResult(None, (ImportIssue(
            None, "caps", f"the table is larger than a case can hold: sections {sections} > {MAX_SECTIONS}; "
            "use a larger max_section_m",
            "sections_over_caps", {"sections": sections, "limit": MAX_SECTIONS},
        ),), summary, label_map)
    try:
        spec = normalize_case_spec(raw)
    except ValidationError as exc:
        return ImportResult(None, tuple(
            ImportIssue(
                None, issue["field"], f"{issue['code']}: {issue['guidance']}",
                f"spec.{issue['code']}", {},
            )
            for issue in (validation_issue(error) for error in exc.errors(include_input=False))
        ), summary, label_map)
    return ImportResult(spec.model_dump(mode="json", by_alias=True, exclude_none=True), (), summary, label_map)


def _cells(pipe: Mapping[str, Any]) -> list[float]:
    stated = pipe.get("segment_lengths_m")
    return list(stated) if stated else [pipe["length_m"] / pipe["sections"]] * pipe["sections"]
