"""Exact recovery of trusted CaseSpec state from compiler-owned GENKEY bytes."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing_extensions import override

from .case_compiler import (
    LEGACY_PROVENANCE_MARKER,
    MATERIAL_LABEL,
    PROVENANCE_MARKER,
    PROVENANCE_MARKER_V3,
    WALL_LABEL,
    _number,
    _trend_anchors,
    derived_output_intervals,
    render_case_spec,
)
from .case_spec import CaseSpec, normalize_case_spec
from .case_spec_validation import JsonObject

_N = r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"
_FLOW_HEAD = re.compile(r"NETWORKCOMPONENT TYPE=FLOWPATH, TAG=([A-Z][A-Z0-9_]*)")
_NODE_HEAD = re.compile(r"NETWORKCOMPONENT TYPE=(NODE|JUNCTIONNODE), TAG=([A-Z][A-Z0-9_]*)")
_GEOMETRY = re.compile(
    rf' GEOMETRY LABEL="G-([A-Z][A-Z0-9_]*)"(?:, XSTART=({_N}) m, YSTART=({_N}) m, ZSTART=({_N}) m)?'
)
_PIPE = re.compile(
    r' PIPE LABEL=([A-Z][A-Z0-9_]*), (?:WALL="' + WALL_LABEL + r'", )?'
    + rf'ROUGHNESS=({_N}) m, '
    + rf'NSEGMENT=(\d+), LSEGMENT=\(([^)]*)\) m, XEND=({_N}) m, YEND=({_N}) m, '
    + rf'ZEND=({_N}) m, DIAMETER=({_N}) m'
)
_LENGTH_PIPE = re.compile(
    r' PIPE LABEL=([A-Z][A-Z0-9_]*), (?:WALL="' + WALL_LABEL + r'", )?'
    + rf'ROUGHNESS=({_N}) m, '
    + rf'NSEGMENT=(\d+), LSEGMENT=\(([^)]*)\) m, LENGTH=({_N}) m, ELEVATION=({_N}) m, '
    + rf'DIAMETER=({_N}) m'
)
_PRESSURE = re.compile(
    rf' PARAMETERS LABEL="([A-Z][A-Z0-9_]*)", TYPE=PRESSURE(?:, X=({_N}) m, Y=({_N}) m, '
    + rf'Z=({_N}) m)?, PRESSURE=({_N}) Pa, TEMPERATURE=({_N}) C'
    + rf'(?:, GASFRACTION=({_N}) -)?(?:, TOTALWATERFRACTION=({_N}) -)?'
    + rf', TIME=0 s, FLUID="([^"\r\n]+)"'
)
_CLOSED = re.compile(
    rf' PARAMETERS LABEL="([A-Z][A-Z0-9_]*)", TYPE=CLOSED(?:, X=({_N}) m, Y=({_N}) m, Z=({_N}) m)?'
)
_OPTIONS = re.compile(
    r"OPTIONS STEADYSTATE=(ON|OFF), COMPOSITIONAL=OFF, FLOWMODEL=OLGAHD(, TEMPERATURE=ADIABATIC)?"
)
_POSITION = re.compile(
    r' POSITION LABEL="([A-Z][A-Z0-9_]*)", PIPE=([A-Z][A-Z0-9_]*), SECTION=(\d+)'
)
_SOURCE = re.compile(
    rf' SOURCE LABEL="([A-Z][A-Z0-9_]*)", POSITION="([A-Z][A-Z0-9_]*)", '
    rf'TIME=\(([^)]*)\) s, MASSFLOW=\(([^)]*)\) kg/s, TEMPERATURE=\(([^)]*)\) C, '
    rf'GASFRACTION=\(([^)]*)\) -, TOTALWATERFRACTION=\(([^)]*)\) -'
)
# genkey-keywords.md lists EQUILIBRIUMMODEL on VALVE. The toolkit accepts the
# compiler line without it, so this pattern stays on the bytes the compiler writes.
_VALVE = re.compile(
    rf' VALVE LABEL="([A-Z][A-Z0-9_]*)", TIME=0 s, PIPE=([A-Z][A-Z0-9_]*), '
    rf'SECTIONBOUNDARY=(\d+), DIAMETER=({_N}) m, OPENING=({_N})'
)
_SCHEDULED_VALVE = re.compile(
    rf' VALVE LABEL="([A-Z][A-Z0-9_]*)", TIME=\(([^)]*)\) s, PIPE=([A-Z][A-Z0-9_]*), '
    rf'SECTIONBOUNDARY=(\d+), DIAMETER=({_N}) m, OPENING=\(([^)]*)\)'
)
_MATERIAL = re.compile(
    rf'MATERIAL LABEL="{MATERIAL_LABEL}", CAPACITY=({_N}) J/kg-K, CONDUCTIVITY=({_N}) W/m-K, '
    rf'DENSITY=({_N}) kg/m3, TYPE=SOLID'
)
_WALL = re.compile(rf'WALL LABEL="{WALL_LABEL}", THICKNESS=\(({_N})\) m, MATERIAL=\("{MATERIAL_LABEL}"\)')
_HEAT_TRANSFER = re.compile(
    r' HEATTRANSFER LABEL="HT_[A-Z][A-Z0-9_]*", PIPE=(?:"[A-Z][A-Z0-9_]*"|\("[^)]*\)), HOUTEROPTION=HGIVEN, '
    + rf'TAMBIENT=({_N}) C, HAMBIENT=({_N}) W/m2-K'
)
_BRANCH_FLUID = re.compile(r' BRANCH FLUID="([^"\r\n]+)"')
_INITIAL = re.compile(
    rf" INITIALCONDITIONS PRESSURE=({_N}) Pa, TEMPERATURE=({_N}) C, VOIDFRACTION=({_N})"
)
_CONNECTION = re.compile(
    r"CONNECTION TERMINALS = \(([A-Z][A-Z0-9_]*) ([A-Z0-9_]+), "
    +
    r"([A-Z][A-Z0-9_]*) (INLET|OUTLET)\)"
)


@dataclass(frozen=True, slots=True)
class UnsupportedSourceError(ValueError):
    reason: str

    @override
    def __str__(self) -> str:
        return (
            "This GENKEY is not an exact CaseSpec compiler artifact. "
            "Review it read-only or rebuild it through CaseSpec before typed editing: "
            f"{self.reason}"
        )


def _blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("NETWORKCOMPONENT TYPE="):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end] != "ENDNETWORKCOMPONENT":
            end += 1
        if end == len(lines):
            raise UnsupportedSourceError("unterminated network component")
        blocks.append((lines[index], lines[index + 1 : end]))
        index = end + 1
    return blocks


_INTEGRATION = re.compile(
    rf"INTEGRATION ENDTIME=({_N}) s(?:, MAXDT=({_N}) s)?, "
    rf"MINDT=({_N}) s, STARTTIME=0 s, DTSTART=({_N}) s"
)
_OUTPUT_LISTS = (
    re.compile(r" OUTPUTDATA VARIABLE=\(([A-Z, ]+)\)"),
    re.compile(r" PROFILEDATA VARIABLE=\(([A-Z, ]+)\)"),
    re.compile(
        r' TRENDDATA POSITION=(?:"[A-Z][A-Z0-9_]*"|\([A-Z0-9_, ]+\)), '
        r"VARIABLE=\(([A-Z, ]+)\)"
    ),
)
_GLOBAL_TREND = re.compile(r"TRENDDATA VARIABLE=([A-Z]+)")
_CADENCE = {
    "output_interval_s": re.compile(rf"OUTPUT DTOUT=({_N}) s"),
    "trend_interval_s": re.compile(rf"TREND DTPLOT=({_N}) s"),
    "profile_interval_s": re.compile(rf"PROFILE DTPLOT=({_N}) s"),
}


def _output_names(lines: list[str]) -> list[str]:
    names: list[str] = []
    for line in lines:
        global_trend = _GLOBAL_TREND.fullmatch(line)
        if global_trend is not None:
            names.append(global_trend[1])
            continue
        for pattern in _OUTPUT_LISTS:
            matched = pattern.fullmatch(line)
            if matched is not None:
                names.extend(matched[1].split(", "))
                break
    if not names:
        raise UnsupportedSourceError("compiler globals are absent or altered")
    return sorted(set(names))


def _globals(lines: list[str]) -> tuple[str, JsonObject, list[str]]:
    pvt_line = next((line for line in lines if line.startswith("FILES PVTFILE=")), "")
    integration_line = next((line for line in lines if line.startswith("INTEGRATION ENDTIME=")), "")
    pvt = re.fullmatch(r'FILES PVTFILE="([^"\r\n]+)"', pvt_line)
    integration_match = _INTEGRATION.fullmatch(integration_line)
    if pvt is None or integration_match is None:
        raise UnsupportedSourceError("compiler globals are absent or altered")
    end_time = float(integration_match[1])
    trend, profile, written = derived_output_intervals(end_time)
    derived = {
        "trend_interval_s": trend,
        "profile_interval_s": profile,
        "output_interval_s": written,
    }
    integration: JsonObject = {"end_time_s": end_time}
    if integration_match[2] is not None:
        integration["max_dt_s"] = float(integration_match[2])
    if integration_match[3] != "0.001":
        integration["min_dt_s"] = float(integration_match[3])
    if integration_match[4] != "1":
        integration["dt_start_s"] = float(integration_match[4])
    for name, pattern in _CADENCE.items():
        matched = next((pattern.fullmatch(line) for line in lines if pattern.fullmatch(line)), None)
        if matched is None:
            raise UnsupportedSourceError("compiler output cadence is absent or altered")
        value = float(matched[1])
        if _number(value) != _number(derived[name]):
            integration[name] = value
    return pvt[1], integration, _output_names(lines)


def _fluid_and_thermal(lines: list[str]) -> tuple[str, JsonObject, bool]:
    fluid = next((m[1] for line in lines if (m := _BRANCH_FLUID.fullmatch(line))), None)
    options = _OPTIONS.fullmatch(lines[1]) if len(lines) > 1 else None
    if fluid is None or options is None:
        raise UnsupportedSourceError("fluid label or temperature option is altered")
    steady_off = options[1] == "OFF"
    if options[2] is not None:
        return fluid, {"model": "adiabatic"}, steady_off
    material = next((m for line in lines if (m := _MATERIAL.fullmatch(line))), None)
    wall = next((m for line in lines if (m := _WALL.fullmatch(line))), None)
    heat = next((m for line in lines if (m := _HEAT_TRANSFER.fullmatch(line))), None)
    if material is None or wall is None or heat is None:
        raise UnsupportedSourceError("ambient heat-exchange definition is altered")
    return fluid, {
        "model": "ambient_h_given",
        "ambient_temperature_c": float(heat[1]),
        "outer_heat_transfer_coefficient_w_m2k": float(heat[2]),
        "wall": {
            "thickness_m": float(wall[1]),
            "material": {
                "heat_capacity_j_kgk": float(material[1]),
                "conductivity_w_mk": float(material[2]),
                "density_kg_m3": float(material[3]),
            },
        },
    }, steady_off


def _csv_numbers(text: str) -> list[float]:
    parts = [part.strip() for part in text.split(",")]
    if not parts or any(part == "" for part in parts):
        raise UnsupportedSourceError("source series is altered")
    try:
        return [float(part) for part in parts]
    except ValueError as exc:
        raise UnsupportedSourceError("source series is altered") from exc


def _source_record(
    flowpath: str, matched: re.Match[str], positions: dict[str, tuple[str, int]]
) -> JsonObject:
    label, position_label, times_text, flows_text, temps_text, gases_text, waters_text = matched.groups()
    position = positions.get(position_label)
    if position is None:
        raise UnsupportedSourceError("source position is absent")
    times = _csv_numbers(times_text)
    flows = _csv_numbers(flows_text)
    temperatures = _csv_numbers(temps_text)
    gases = _csv_numbers(gases_text)
    waters = _csv_numbers(waters_text)
    width = len(times)
    if width == 0 or any(len(column) != width for column in (flows, temperatures, gases, waters)):
        raise UnsupportedSourceError("source series is altered")
    record: JsonObject = {
        "label": label,
        "flowpath": flowpath,
        "pipe": position[0],
        "section": position[1],
        "time_s": times[0],
        "mass_flow_kg_s": flows[0],
        "temperature_c": temperatures[0],
        "gas_fraction": gases[0],
        "total_water_fraction": waters[0],
    }
    if width > 1:
        record["series"] = [
            {
                "time_s": times[index],
                "mass_flow_kg_s": flows[index],
                "temperature_c": temperatures[index],
                "gas_fraction": gases[index],
                "total_water_fraction": waters[index],
            }
            for index in range(width)
        ]
    return record


def _valve_position(section: int, sections: int) -> float:
    if section < 1 or section > sections:
        raise UnsupportedSourceError("valve section is outside the pipe")
    candidate = 1.0 if section == sections else (section + 0.5) / sections
    mapped = min(sections, max(1, int(candidate * sections)))
    if mapped != section or not 0.0 <= candidate <= 1.0:
        raise UnsupportedSourceError("valve section does not round-trip")
    return candidate


def _boundary_node(
    label: str, kind: str, boundaries: dict[str, tuple[float, float]]
) -> JsonObject:
    if label not in boundaries:
        raise UnsupportedSourceError("boundary pressure or temperature is absent")
    pressure, temperature = boundaries[label]
    return {"label": label, "kind": kind, "pressure_pa": pressure, "temperature_c": temperature}


def _flowpath_body(
    label: str, body: list[str]
) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject], list[tuple[str, str, int]]]:
    geometry = next((_GEOMETRY.fullmatch(line) for line in body if line.startswith(" GEOMETRY")), None)
    if geometry is None or geometry[1] != label:
        raise UnsupportedSourceError("flowpath geometry is not compiler-owned")
    start = None if geometry[2] is None else [float(geometry[index]) for index in range(2, 5)]
    pipes: list[JsonObject] = []
    positions: dict[str, tuple[str, int]] = {}
    sources: list[JsonObject] = []
    equipment: list[JsonObject] = []
    for line in body:
        pipe = _PIPE.fullmatch(line) if start is not None else None
        if pipe is not None:
            sections = int(pipe[3])
            lengths = pipe[4].split(",")
            if len(lengths) != sections:
                raise UnsupportedSourceError("segment count disagrees with LSEGMENT")
            end = [float(pipe[index]) for index in range(5, 8)]
            record: JsonObject = {
                "label": pipe[1], "centerline_m": [start, end],
                "diameter_m": float(pipe[8]), "roughness_m": float(pipe[2]),
                "sections": sections,
            }
            if len(set(lengths)) > 1:
                record["segment_lengths_m"] = [float(item) for item in lengths]
            pipes.append(record)
            start = end
            continue
        length_pipe = _LENGTH_PIPE.fullmatch(line) if start is None else None
        if length_pipe is not None:
            sections = int(length_pipe[3])
            lengths = length_pipe[4].split(",")
            if len(lengths) != sections:
                raise UnsupportedSourceError("segment count disagrees with LSEGMENT")
            record = {
                "label": length_pipe[1], "length_m": float(length_pipe[5]),
                "elevation_m": float(length_pipe[6]), "diameter_m": float(length_pipe[7]),
                "roughness_m": float(length_pipe[2]), "sections": sections,
            }
            if len(set(lengths)) > 1:
                record["segment_lengths_m"] = [float(item) for item in lengths]
            pipes.append(record)
            continue
        position = _POSITION.fullmatch(line)
        if position is not None:
            positions[position[1]] = (position[2], int(position[3]))
            continue
        source = _SOURCE.fullmatch(line)
        if source is not None:
            sources.append(_source_record(label, source, positions))
            continue
        if line.startswith(" SOURCE "):
            raise UnsupportedSourceError("source line is outside compiler grammar")
        valve = _VALVE.fullmatch(line)
        scheduled = None if valve is not None else _SCHEDULED_VALVE.fullmatch(line)
        if valve is not None or scheduled is not None:
            if scheduled is not None:
                valve_label, pipe_label, section_text, diameter = (
                    scheduled[1], scheduled[3], scheduled[4], scheduled[5]
                )
                times, openings = _csv_numbers(scheduled[2]), _csv_numbers(scheduled[6])
                if len(times) != len(openings):
                    raise UnsupportedSourceError("valve schedule is altered")
            else:
                valve_label, pipe_label, section_text, diameter = valve[1], valve[2], valve[3], valve[4]
                times, openings = [0.0], [float(valve[5])]
            pipe_sections = next(
                (int(item["sections"]) for item in pipes if item["label"] == pipe_label),
                None,
            )
            if pipe_sections is None:
                raise UnsupportedSourceError("valve pipe is absent")
            record = {
                "kind": "valve",
                "label": valve_label,
                "flowpath": label,
                "pipe": pipe_label,
                "position": _valve_position(int(section_text), pipe_sections),
                "diameter_m": float(diameter),
                "opening": openings[0],
            }
            if scheduled is not None:
                record["schedule"] = [
                    {"time_s": time, "opening": opening} for time, opening in zip(times, openings)
                ]
            equipment.append(record)
            continue
        if line.startswith(" VALVE "):
            raise UnsupportedSourceError("valve line is outside compiler grammar")
    if not pipes:
        raise UnsupportedSourceError("flowpath geometry is not compiler-owned")
    referenced = {
        str(source.group(2))
        for line in body
        if (source := _SOURCE.fullmatch(line))
    }
    pipe_index = {str(pipe["label"]): index for index, pipe in enumerate(pipes)}
    anchors = [
        (name, pipe_name, section)
        for name, (pipe_name, section) in positions.items()
        if name not in referenced and pipe_name in pipe_index
    ]
    anchors.sort(key=lambda item: (pipe_index[item[1]], item[2], item[0]))
    return pipes, sources, equipment, anchors


def _network(
    lines: list[str],
) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject], list[JsonObject], list[JsonObject] | None]:
    flowpaths: list[JsonObject] = []
    node_types: dict[str, str] = {}
    boundaries: dict[str, tuple[float, float]] = {}
    fractions: dict[str, tuple[float | None, float | None]] = {}
    closed: set[str] = set()
    sources: list[JsonObject] = []
    equipment: list[JsonObject] = []
    anchors_by_flowpath: dict[str, list[tuple[str, str, int]]] = {}
    defaults_match = True
    for head, body in _blocks(lines):
        flow = _FLOW_HEAD.fullmatch(head)
        node = _NODE_HEAD.fullmatch(head)
        if flow is not None:
            pipes, flow_sources, flow_valves, anchors = _flowpath_body(flow[1], body)
            flowpaths.append({"label": flow[1], "pipes": pipes})
            sources.extend(flow_sources)
            equipment.extend(flow_valves)
            anchors_by_flowpath[flow[1]] = anchors
        elif node is not None:
            node_types[node[2]] = node[1]
            pressure = next((_PRESSURE.fullmatch(line) for line in body if "TYPE=PRESSURE" in line), None)
            if pressure is not None:
                boundaries[node[2]] = (float(pressure[5]), float(pressure[6]))
                fractions[node[2]] = (
                    None if pressure[7] is None else float(pressure[7]),
                    None if pressure[8] is None else float(pressure[8]),
                )
            if any(_CLOSED.fullmatch(line) for line in body):
                closed.add(node[2])
    endpoints: dict[str, dict[str, str]] = defaultdict(dict)
    for line in lines:
        connection = _CONNECTION.fullmatch(line)
        if connection is not None:
            endpoints[connection[3]][connection[4]] = connection[1]
    for flowpath in flowpaths:
        identity = str(flowpath["label"])
        if set(endpoints[identity]) != {"INLET", "OUTLET"}:
            raise UnsupportedSourceError("flowpath endpoint connections are incomplete")
        flowpath["from"] = endpoints[identity]["INLET"]
        flowpath["to"] = endpoints[identity]["OUTLET"]
    incoming = {label: 0 for label in node_types}
    outgoing = {label: 0 for label in node_types}
    for flowpath in flowpaths:
        outgoing[str(flowpath["from"])] += 1
        incoming[str(flowpath["to"])] += 1
    nodes: list[JsonObject] = []
    for label, node_type in node_types.items():
        if node_type == "JUNCTIONNODE":
            nodes.append({"label": label, "kind": "junction"})
            continue
        if label in closed:
            if label in boundaries:
                raise UnsupportedSourceError("closed node carries a pressure boundary")
            nodes.append({"label": label, "kind": "closed"})
            continue
        gas, water = fractions.get(label, (None, None))
        if incoming[label] == 0 and outgoing[label] == 1:
            kind = "source"
        elif incoming[label] == 1 and outgoing[label] == 0:
            kind = "sink"
        else:
            raise UnsupportedSourceError("node degree is outside compiler grammar")
        if gas is None or water is None:
            raise UnsupportedSourceError("pressure node is missing a phase fraction")
        boundary = _boundary_node(label, kind, boundaries)
        boundary["gas_fraction"] = gas
        boundary["total_water_fraction"] = water
        nodes.append(boundary)
    stated: list[JsonObject] = []
    for flowpath in flowpaths:
        identity = str(flowpath["label"])
        anchors = anchors_by_flowpath.get(identity, [])
        if anchors != _trend_anchors(flowpath, {}):
            defaults_match = False
        stated.extend(
            {"label": name, "pipe": pipe, "section": section}
            for name, pipe, section in anchors
        )
    return nodes, flowpaths, sources, equipment, None if defaults_match else stated


def _flowpath_starts(lines: list[str]) -> dict[str, tuple[str, str, str]]:
    """INITIALCONDITIONS (pressure, temperature, void) per flowpath, in file order."""
    starts: dict[str, tuple[str, str, str]] = {}
    current: str | None = None
    for line in lines:
        if (head := _FLOW_HEAD.fullmatch(line)) is not None:
            current = head[1]
        elif _NODE_HEAD.fullmatch(line) is not None:
            current = None
        elif (start := _INITIAL.fullmatch(line)) is not None:
            if current is None or current in starts:
                raise UnsupportedSourceError("initial conditions sit outside one flowpath")
            starts[current] = start.groups()
    return starts


def recover_case_spec(source: Path) -> CaseSpec:
    """Recover only when re-rendering proves byte-for-byte compiler ownership."""
    try:
        content = source.read_bytes()
        text = content.decode("utf-8")
        lines = text.splitlines()
        if lines and lines[0] == LEGACY_PROVENANCE_MARKER:
            raise UnsupportedSourceError(
                "it was compiled by CaseSpec v1, which had no fluid label, boundary "
                "temperature or heat-exchange inputs and was never solver-valid; "
                "rebuild it as CaseSpec v2 with those inputs stated by the user"
            )
        if not lines or lines[0] not in {PROVENANCE_MARKER, PROVENANCE_MARKER_V3}:
            raise UnsupportedSourceError("provenance marker is absent")
        version = "3" if lines[0] == PROVENANCE_MARKER_V3 else "2"
        pvt, integration, outputs = _globals(lines)
        fluid_label, thermal, steady_off = _fluid_and_thermal(lines)
        if steady_off:
            integration["steady_state"] = False
        nodes, flowpaths, sources, equipment, trends = _network(lines)
        payload: JsonObject = {
            "version": version, "nodes": nodes, "flowpaths": flowpaths,
            "pvt_reference": pvt, "fluid_label": fluid_label, "thermal": thermal,
            "integration": integration, "outputs": outputs,
        }
        if sources:
            payload["massflow_sources"] = sources
        if equipment:
            payload["equipment"] = equipment
        if trends:
            payload["trend_positions"] = trends
        starts = _flowpath_starts(lines)
        if len({(pressure, temperature) for pressure, temperature, _void in starts.values()}) > 1:
            raise UnsupportedSourceError("flowpaths start from different initial conditions")
        if starts:
            # The first flowpath's void fraction is the shared one; the others that differ
            # carry their own, which is how the compiler wrote them.
            pressure, temperature, void = next(iter(starts.values()))
            payload["initial_conditions"] = {
                "pressure_pa": float(pressure), "temperature_c": float(temperature), "void_fraction": float(void),
            }
            for flowpath in flowpaths:
                own = starts.get(str(flowpath["label"]))
                if own is not None and float(own[2]) != float(void):
                    flowpath["initial_void_fraction"] = float(own[2])
        spec = normalize_case_spec(payload)
    except (OSError, UnicodeError, KeyError, ValueError) as exc:
        if isinstance(exc, UnsupportedSourceError):
            raise
        raise UnsupportedSourceError(type(exc).__name__) from exc
    if render_case_spec(spec) != content:
        raise UnsupportedSourceError("byte-exact compiler round trip disagrees")
    return spec
