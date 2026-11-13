"""Deterministic, read-only CaseSpec v2 to OLGA GENKEY compiler."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .case_companion import verify_pvt_companion
from .case_compiler_toolkit import Geometry, ToolkitVerification, verify_with_toolkit
from .genkey_tool_runner import file_sha256

MAX_COMPILED_BYTES = 1_048_576
PROVENANCE_MARKER = "! Deterministic CaseSpec v2 compilation"
PROVENANCE_MARKER_V3 = "! Deterministic CaseSpec v3 compilation"
LEGACY_PROVENANCE_MARKER = "! Deterministic CaseSpec v1 compilation"
# Identifiers only: every physical value comes from the user's spec.
MATERIAL_LABEL = "CASESPEC_MATERIAL"
WALL_LABEL = "CASESPEC_WALL"
# Each name is emitted only in the keyword contexts that name it.
# output: genkey-keywords.md OUTPUTDATA table 404-416 (LIQC at 416); owner genkey OUTPUTDATA line 47.
# profile: genkey-keywords.md PROFILEDATA example 480; owner genkey PROFILEDATA line 48. Neither lists LIQC or GT.
# trend_position: owner genkey TRENDDATA POSITION VARIABLE list lines 49-50 (GT is only there);
#   genkey-keywords.md nested TRENDDATA VARIABLE=PT line 529.
# trend_global: genkey-keywords.md global TRENDDATA example line 165 is VARIABLE=LIQC only.
#   OLGA 2022.1.0 rejects HOL and PT as case-level trend variables. The name list at
#   line 161 is not a case-level allow-list. TM, GT, QLT and ID have no global example.
_OUTPUT_CONTEXTS = {
    "PT": frozenset({"output", "profile", "trend_position"}),
    "TM": frozenset({"output", "profile", "trend_position"}),
    "HOL": frozenset({"output", "profile", "trend_position"}),
    "GT": frozenset({"trend_position"}),
    "QLT": frozenset({"output", "profile", "trend_position"}),
    "ID": frozenset({"output", "profile", "trend_position"}),
    "LIQC": frozenset({"output", "trend_global"}),
}


class CaseCompileError(ValueError):
    """A candidate cannot be represented and verified as supported GENKEY."""


@dataclass(frozen=True)
class CompilationResult:
    compiled_bytes: bytes
    sha256: str
    validation: ToolkitVerification
    topology_edges: tuple[tuple[str, str, str], ...]
    section_count: int
    source_mutated: bool
    companion_status: str = "unverified"
    warnings: tuple[str, ...] = (
        "PVT companion existence is verified only in a contained publish context.",
    )

    @property
    def text(self) -> str:
        return self.compiled_bytes.decode("utf-8")

    def to_public_dict(self) -> dict[str, object]:
        """Return the path-private JSON shape consumed by Chat preview."""
        return {
            "compiled_text": self.text,
            "compiled_hash": self.sha256,
            "validation": {
                "clean": self.validation.clean,
                "parser_clean": self.validation.parser_clean,
                "validator_clean": self.validation.validator_clean,
                "diagnostics": list(self.validation.diagnostics),
            },
            "topology": {
                "edges": [
                    {"from": source, "to": target, "label": label}
                    for source, target, label in self.topology_edges
                ],
            },
            "geometry": {"sections": self.section_count},
            "source_mutated": self.source_mutated,
            "companion": {"status": self.companion_status, "warnings": list(self.warnings)},
        }


def _paren(values: list[float]) -> str:
    return "(" + ", ".join(_number(value) for value in values) + ")"


def _number(value: float | int) -> str:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise CaseCompileError("CaseSpec contains a non-finite number.")
    if numeric == 0:
        return "0"
    # Positional notation: GENKEY readers are not guaranteed to accept exponents.
    text = format(Decimal(format(numeric, ".15g")), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _normalized(raw: Mapping[str, Any] | Any) -> dict[str, Any]:
    from .case_spec import CaseSpec, normalize_case_spec

    model = raw if isinstance(raw, CaseSpec) else normalize_case_spec(raw)
    normalized = model.model_dump(mode="json", by_alias=True)
    if any(character in normalized["pvt_reference"] for character in '\\",='):
        raise CaseCompileError("PVT reference contains unsupported GENKEY delimiters.")
    return normalized


def _point_text(point: list[float]) -> str:
    return ", ".join(
        f"{axis}={_number(value)} m" for axis, value in zip(("X", "Y", "Z"), point, strict=True)
    )


def _start_point_text(point: list[float]) -> str:
    return ", ".join(
        f"{axis}START={_number(value)} m"
        for axis, value in zip(("X", "Y", "Z"), point, strict=True)
    )


def _segment_lengths(pipe: dict[str, Any]) -> list[str]:
    stated = pipe.get("segment_lengths_m")
    if stated:
        return [_number(value) for value in stated]
    sections = int(pipe["sections"])
    if pipe.get("length_m") is not None:
        length = float(pipe["length_m"])
    else:
        start, end = pipe["centerline_m"]
        length = math.dist(start, end)
    return [_number(length / sections)] * sections


def _pipe_line(pipe: dict[str, Any], wall: bool) -> str:
    sections = int(pipe["sections"])
    lengths = ",".join(_segment_lengths(pipe))
    wall_text = f'WALL="{WALL_LABEL}", ' if wall else ""
    head = (
        f" PIPE LABEL={pipe['label']}, {wall_text}ROUGHNESS={_number(pipe['roughness_m'])} m, "
        f"NSEGMENT={sections}, LSEGMENT=({lengths}) m, "
    )
    if pipe.get("length_m") is not None:
        return (
            f"{head}LENGTH={_number(pipe['length_m'])} m, "
            f"ELEVATION={_number(pipe['elevation_m'])} m, DIAMETER={_number(pipe['diameter_m'])} m"
        )
    if len(pipe["centerline_m"]) != 2:
        raise CaseCompileError("Each v2 pipe centerline requires exactly two endpoints.")
    end = pipe["centerline_m"][1]
    return (
        f"{head}XEND={_number(end[0])} m, YEND={_number(end[1])} m, "
        f"ZEND={_number(end[2])} m, DIAMETER={_number(pipe['diameter_m'])} m"
    )


def _heat_transfer_line(flowpath: dict[str, Any], thermal: dict[str, Any]) -> str:
    labels = [pipe["label"] for pipe in flowpath["pipes"]]
    pipes = f'"{labels[0]}"' if len(labels) == 1 else "(" + ",".join(f'"{item}"' for item in labels) + ")"
    return (
        f' HEATTRANSFER LABEL="HT_{flowpath["label"]}", PIPE={pipes}, HOUTEROPTION=HGIVEN, '
        f"TAMBIENT={_number(thermal['ambient_temperature_c'])} C, "
        f"HAMBIENT={_number(thermal['outer_heat_transfer_coefficient_w_m2k'])} W/m2-K"
    )


def _valve_lines(flowpath: dict[str, Any], equipment: list[dict[str, Any]]) -> list[str]:
    pipes = {pipe["label"]: pipe for pipe in flowpath["pipes"]}
    lines: list[str] = []
    for valve in equipment:
        if valve["flowpath"] != flowpath["label"]:
            continue
        nsegment = int(pipes[valve["pipe"]]["sections"])
        section = max(1, int(float(valve["position"]) * nsegment))
        section = min(section, nsegment)
        schedule = valve.get("schedule")
        if schedule:
            time_text = f"{_paren([point['time_s'] for point in schedule])} s"
            opening_text = _paren([point["opening"] for point in schedule])
        else:
            time_text, opening_text = "0 s", _number(valve["opening"])
        lines.append(
            f' VALVE LABEL="{valve["label"]}", TIME={time_text}, PIPE={valve["pipe"]}, '
            f'SECTIONBOUNDARY={section}, DIAMETER={_number(valve["diameter_m"])} m, '
            f'OPENING={opening_text}'
        )
    return lines


def _massflow_lines(flowpath_label: str, sources: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for source in sources:
        if source["flowpath"] != flowpath_label:
            continue
        lines.append(
            f' POSITION LABEL="POS_{source["label"]}", PIPE={source["pipe"]}, '
            f'SECTION={int(source["section"])}'
        )
        series = source.get("series") or ()
        if series:
            times = [point["time_s"] for point in series]
            flows = [point["mass_flow_kg_s"] for point in series]
            temperatures = [point["temperature_c"] for point in series]
            gases = [point["gas_fraction"] for point in series]
            waters = [point["total_water_fraction"] for point in series]
        else:
            times = [source["time_s"]]
            flows = [source["mass_flow_kg_s"]]
            temperatures = [source["temperature_c"]]
            gases = [source["gas_fraction"]]
            waters = [source["total_water_fraction"]]
        lines.append(
            f' SOURCE LABEL="{source["label"]}", POSITION="POS_{source["label"]}", '
            f"TIME={_paren(times)} s, "
            f"MASSFLOW={_paren(flows)} kg/s, "
            f"TEMPERATURE={_paren(temperatures)} C, "
            f"GASFRACTION={_paren(gases)} -, "
            f"TOTALWATERFRACTION={_paren(waters)} -"
        )
    return lines


def _trend_anchors(
    flowpath: dict[str, Any], spec: dict[str, Any]
) -> list[tuple[str, str, int]]:
    """Observation points for one flowpath.

    A user list replaces the default. An absent list records section 1 of the
    first pipe and the last section of the last pipe. One section collapses
    to the outlet label already used by a single-position case.
    """
    pipes = flowpath["pipes"]
    pipe_index = {pipe["label"]: index for index, pipe in enumerate(pipes)}
    stated = spec.get("trend_positions") or ()
    if stated:
        anchors = [
            (point["label"], point["pipe"], int(point["section"]))
            for point in stated
            if point["pipe"] in pipe_index
        ]
        anchors.sort(key=lambda item: (pipe_index[item[1]], item[2], item[0]))
        return anchors
    first = pipes[0]
    last = pipes[-1]
    outlet = (f'POS_{flowpath["label"]}', last["label"], int(last["sections"]))
    inlet = (f'POS_{flowpath["label"]}_1', first["label"], 1)
    if inlet[1:] == outlet[1:]:
        return [outlet]
    return [inlet, outlet]


def _uses_length(spec: dict[str, Any]) -> bool:
    return any(
        pipe.get("length_m") is not None for flowpath in spec["flowpaths"] for pipe in flowpath["pipes"]
    )


def _node_points(spec: dict[str, Any]) -> dict[str, list[float]]:
    points: dict[str, list[float]] = {}
    if _uses_length(spec):
        return points
    for flowpath in spec["flowpaths"]:
        points.setdefault(flowpath["from"], flowpath["pipes"][0]["centerline_m"][0])
        points.setdefault(flowpath["to"], flowpath["pipes"][-1]["centerline_m"][-1])
    return points


def _junction_terminal_map(spec: dict[str, Any]) -> dict[tuple[str, str], str]:
    flowpaths = spec["flowpaths"]
    result: dict[tuple[str, str], str] = {}
    for node in spec["nodes"]:
        if node["kind"] != "junction":
            continue
        incoming = [item for item in flowpaths if item["to"] == node["label"]]
        outgoing = [item for item in flowpaths if item["from"] == node["label"]]
        if len(incoming) == 1 and outgoing:
            result[(node["label"], incoming[0]["label"])] = "MIXTERM"
            arms = outgoing
        elif len(outgoing) == 1 and incoming:
            result[(node["label"], outgoing[0]["label"])] = "MIXTERM"
            arms = incoming
        else:
            raise CaseCompileError("A junction requires exactly one split inlet or merge outlet.")
        for index, flowpath in enumerate(arms, 1):
            result[(node["label"], flowpath["label"])] = f"FLOWTERM_{index}"
    return result


def _connections(spec: dict[str, Any]) -> list[str]:
    node_kinds = {node["label"]: node["kind"] for node in spec["nodes"]}
    junction_terminals = _junction_terminal_map(spec)
    lines: list[str] = []
    for flowpath in spec["flowpaths"]:
        for endpoint, terminal in ((flowpath["from"], "INLET"), (flowpath["to"], "OUTLET")):
            endpoint_terminal = (
                junction_terminals[(endpoint, flowpath["label"])]
                if node_kinds[endpoint] == "junction"
                else "FLOWTERM_1"
            )
            lines.append(
                "CONNECTION TERMINALS = "
                f"({endpoint} {endpoint_terminal}, {flowpath['label']} {terminal})"
            )
    return lines


def derived_output_intervals(end_time_s: float) -> tuple[float, float, float]:
    """Return trend, profile and output intervals when the user leaves them unset.

    trend = end_time/60, profile = end_time/4, output = end_time.
    max_dt_s is never derived.
    """
    end = float(end_time_s)
    return end / 60, end / 4, end


def _output_cadence(integration: Mapping[str, Any]) -> tuple[float, float, float, float | None]:
    end = float(integration["end_time_s"])
    trend, profile, output = derived_output_intervals(end)
    if integration.get("trend_interval_s") is not None:
        trend = float(integration["trend_interval_s"])
    if integration.get("profile_interval_s") is not None:
        profile = float(integration["profile_interval_s"])
    if integration.get("output_interval_s") is not None:
        output = float(integration["output_interval_s"])
    max_dt = integration.get("max_dt_s")
    if max_dt is not None and float(max_dt) > end / 10:
        raise CaseCompileError("max_dt_s is larger than end_time_s/10.")
    mindt = integration.get("min_dt_s")
    floor = 0.001 if mindt is None else float(mindt)
    for interval in (trend, profile, output):
        if interval < floor:
            raise CaseCompileError("an output interval is shorter than MINDT.")
        if end / interval > 100_000:
            raise CaseCompileError("an output interval asks for too many samples.")
    return trend, profile, output, None if max_dt is None else float(max_dt)


def _names_in(outputs: tuple[str, ...] | list[str], context: str) -> tuple[str, ...]:
    return tuple(name for name in outputs if context in _OUTPUT_CONTEXTS[name])


def _joined(names: tuple[str, ...]) -> str:
    return ", ".join(names)


def render_case_spec(raw: Mapping[str, Any] | Any) -> bytes:
    spec = _normalized(raw)
    thermal = spec["thermal"]
    ambient = thermal["model"] == "ambient_h_given"
    outputs = spec["outputs"]
    # Absent intervals: trend = end_time/60, profile = end_time/4, output = end_time.
    # max_dt_s is emitted only when stated and at most end_time/10.
    trend_s, profile_s, output_s, max_dt_s = _output_cadence(spec["integration"])
    integration_spec = spec["integration"]
    mindt = (
        "0.001"
        if integration_spec.get("min_dt_s") is None
        else _number(integration_spec["min_dt_s"])
    )
    dt_start = (
        "1"
        if integration_spec.get("dt_start_s") is None
        else _number(integration_spec["dt_start_s"])
    )
    steady = "OFF" if integration_spec.get("steady_state") is False else "ON"
    integration = f"INTEGRATION ENDTIME={_number(integration_spec['end_time_s'])} s"
    if max_dt_s is not None:
        integration += f", MAXDT={_number(max_dt_s)} s"
    integration += f", MINDT={mindt} s, STARTTIME=0 s, DTSTART={dt_start} s"
    options = f"OPTIONS STEADYSTATE={steady}, COMPOSITIONAL=OFF, FLOWMODEL=OLGAHD"
    v3 = spec["version"] == "3"
    length_geometry = _uses_length(spec)
    lines = [
        PROVENANCE_MARKER_V3 if v3 else PROVENANCE_MARKER,
        options if ambient else f"{options}, TEMPERATURE=ADIABATIC",
        f'CASE AUTHOR=OLGACOMPANION, PROJECT=CASESPEC, TITLE="CaseSpec v{spec["version"]}"',
        f'FILES PVTFILE="{spec["pvt_reference"]}"',
        integration,
        f"OUTPUT DTOUT={_number(output_s)} s",
        f"TREND DTPLOT={_number(trend_s)} s",
        f"PROFILE DTPLOT={_number(profile_s)} s",
        *(f"TRENDDATA VARIABLE={name}" for name in _names_in(outputs, "trend_global")),
    ]
    if ambient:
        wall = thermal["wall"]
        material = wall["material"]
        lines.extend([
            f'MATERIAL LABEL="{MATERIAL_LABEL}", CAPACITY={_number(material["heat_capacity_j_kgk"])} J/kg-K, '
            f"CONDUCTIVITY={_number(material['conductivity_w_mk'])} W/m-K, "
            f"DENSITY={_number(material['density_kg_m3'])} kg/m3, TYPE=SOLID",
            f'WALL LABEL="{WALL_LABEL}", THICKNESS=({_number(wall["thickness_m"])}) m, '
            f'MATERIAL=("{MATERIAL_LABEL}")',
        ])
    initial = spec.get("initial_conditions")
    for flowpath in spec["flowpaths"]:
        void = flowpath.get("initial_void_fraction")
        initial_lines = [] if initial is None else [
            f' INITIALCONDITIONS PRESSURE={_number(initial["pressure_pa"])} Pa, '
            f'TEMPERATURE={_number(initial["temperature_c"])} C, '
            f'VOIDFRACTION={_number(initial["void_fraction"] if void is None else void)}'
        ]
        geometry = f' GEOMETRY LABEL="G-{flowpath["label"]}"'
        if not length_geometry:
            geometry += f', {_start_point_text(flowpath["pipes"][0]["centerline_m"][0])}'
        lines.extend([
            f"NETWORKCOMPONENT TYPE=FLOWPATH, TAG={flowpath['label']}",
            f' PARAMETERS LABEL="{flowpath["label"]}"',
            f' BRANCH FLUID="{spec["fluid_label"]}"',
            *initial_lines,
            geometry,
            *(_pipe_line(pipe, ambient) for pipe in flowpath["pipes"]),
            *([_heat_transfer_line(flowpath, thermal)] if ambient else []),
            *_massflow_lines(flowpath["label"], spec.get("massflow_sources") or ()),
            *_valve_lines(flowpath, spec.get("equipment") or ()),
            *(
                f' POSITION LABEL="{label}", PIPE={pipe}, SECTION={section}'
                for label, pipe, section in _trend_anchors(flowpath, spec)
            ),
        ])
        output_names = _names_in(outputs, "output")
        profile_names = _names_in(outputs, "profile")
        trend_names = _names_in(outputs, "trend_position")
        if output_names:
            lines.append(f" OUTPUTDATA VARIABLE=({_joined(output_names)})")
        if profile_names:
            lines.append(f" PROFILEDATA VARIABLE=({_joined(profile_names)})")
        anchors = _trend_anchors(flowpath, spec)
        if trend_names and anchors:
            if len(anchors) == 1:
                position = f'"{anchors[0][0]}"'
            else:
                position = "(" + ", ".join(label for label, _pipe, _section in anchors) + ")"
            lines.append(
                f" TRENDDATA POSITION={position}, VARIABLE=({_joined(trend_names)})"
            )
        lines.append("ENDNETWORKCOMPONENT")
    node_points = _node_points(spec)
    for node in spec["nodes"]:
        if node["kind"] == "junction":
            lines.extend([
                f"NETWORKCOMPONENT TYPE=JUNCTIONNODE, TAG={node['label']}",
                f' PARAMETERS LABEL="{node["label"]}"',
                "ENDNETWORKCOMPONENT",
            ])
            continue
        point = "" if length_geometry else f", {_point_text(node_points[node['label']])}"
        if node["kind"] == "closed":
            parameters = f'LABEL="{node["label"]}", TYPE=CLOSED{point}'
        else:
            parameters = (
                f'LABEL="{node["label"]}", TYPE=PRESSURE{point}, '
                f"PRESSURE={_number(node['pressure_pa'])} Pa, "
                f"TEMPERATURE={_number(node['temperature_c'])} C"
            )
            parameters += (
                f", GASFRACTION={_number(node['gas_fraction'])} -, "
                f"TOTALWATERFRACTION={_number(node['total_water_fraction'])} -, "
                f'TIME=0 s, FLUID="{spec["fluid_label"]}"'
            )
        lines.extend([
            f"NETWORKCOMPONENT TYPE=NODE, TAG={node['label']}",
            f" PARAMETERS {parameters}",
            "ENDNETWORKCOMPONENT",
        ])
    lines.extend([*_connections(spec), "ENDCASE", ""])
    result = "\n".join(lines).encode("utf-8")
    if len(result) > MAX_COMPILED_BYTES:
        raise CaseCompileError("Compiled GENKEY exceeds the output limit.")
    return result


def _expected_geometry(spec: dict[str, Any]) -> Geometry:
    rows: list[Any] = []
    for flowpath in spec["flowpaths"]:
        for pipe in flowpath["pipes"]:
            segments = tuple(float(value) for value in _segment_lengths(pipe))
            if pipe.get("length_m") is not None:
                rows.append((
                    flowpath["label"], pipe["label"], "length",
                    float(_number(pipe["length_m"])), float(_number(pipe["elevation_m"])),
                    float(pipe["diameter_m"]), int(pipe["sections"]), segments,
                ))
                continue
            start, end = pipe["centerline_m"]
            rows.append((
                flowpath["label"], pipe["label"], tuple(map(float, start)), tuple(map(float, end)),
                float(pipe["diameter_m"]), int(pipe["sections"]), segments,
            ))
    return tuple(sorted(rows))


def _expected_thermal(spec: dict[str, Any]) -> tuple[Any, ...]:
    thermal = spec["thermal"]
    if thermal["model"] == "adiabatic":
        return ("adiabatic",)
    wall, material = thermal["wall"], thermal["wall"]["material"]
    rows = tuple(sorted(
        (
            f"HT_{flowpath['label']}",
            tuple(pipe["label"] for pipe in flowpath["pipes"]),
            float(_number(thermal["ambient_temperature_c"])),
            float(_number(thermal["outer_heat_transfer_coefficient_w_m2k"])),
        )
        for flowpath in spec["flowpaths"]
    ))
    return (
        "ambient_h_given", rows,
        (((float(_number(wall["thickness_m"])),), (MATERIAL_LABEL,)),),
        ((
            float(_number(material["conductivity_w_mk"])),
            float(_number(material["heat_capacity_j_kgk"])),
            float(_number(material["density_kg_m3"])),
        ),),
    )


def compile_case_spec(
    raw: Mapping[str, Any] | Any,
    owner_source: Path | str | None = None,
    *,
    verify: Callable[[str], ToolkitVerification] = verify_with_toolkit,
    pending_companion: str | None = None,
) -> CompilationResult:
    owner = Path(owner_source) if owner_source is not None else None
    before = file_sha256(owner) if owner is not None else None
    expected = _normalized(raw)
    companion_status, companion_warnings = verify_pvt_companion(
        owner, expected["pvt_reference"], expected["fluid_label"], pending=pending_companion
    )
    compiled = render_case_spec(raw)
    validation = verify(compiled.decode("utf-8"))
    if not validation.clean:
        reason = "parser/validator disagreement" if validation.parser_clean != validation.validator_clean else "toolkit verification failure"
        raise CaseCompileError(f"Compiled GENKEY failed closed: {reason}.")
    edges = tuple(sorted((item["from"], item["to"], item["label"]) for item in expected["flowpaths"]))
    sections = sum(pipe["sections"] for item in expected["flowpaths"] for pipe in item["pipes"])
    junction_map = _junction_terminal_map(expected)
    expected_terminals = tuple(sorted(
        (endpoint, flowpath["label"], side, junction_map[(endpoint, flowpath["label"])])
        for flowpath in expected["flowpaths"]
        for endpoint, side in ((flowpath["from"], "INLET"), (flowpath["to"], "OUTLET"))
        if (endpoint, flowpath["label"]) in junction_map
    ))
    if validation.topology_edges and validation.topology_edges != edges:
        raise CaseCompileError("Compiled GENKEY topology disagrees with CaseSpec.")
    if validation.section_count and validation.section_count != sections:
        raise CaseCompileError("Compiled GENKEY geometry disagrees with CaseSpec.")
    if validation.junction_terminals and validation.junction_terminals != expected_terminals:
        raise CaseCompileError("Compiled GENKEY junction terminals disagree with CaseSpec.")
    if validation.geometry and validation.geometry != _expected_geometry(expected):
        raise CaseCompileError("Compiled GENKEY coordinates or segments disagree with CaseSpec.")
    if validation.pvt_reference and validation.pvt_reference != expected["pvt_reference"]:
        raise CaseCompileError("Compiled GENKEY PVT reference disagrees with CaseSpec.")
    if validation.end_time_s and validation.end_time_s != expected["integration"]["end_time_s"]:
        raise CaseCompileError("Compiled GENKEY integration disagrees with CaseSpec.")
    expected_outputs = _names_in(expected["outputs"], "output")
    if validation.outputs and validation.outputs != expected_outputs:
        raise CaseCompileError("Compiled GENKEY outputs disagree with CaseSpec.")
    if validation.fluid_labels and validation.fluid_labels != (expected["fluid_label"],):
        raise CaseCompileError("Compiled GENKEY fluid label disagrees with CaseSpec.")
    if validation.thermal and validation.thermal != _expected_thermal(expected):
        raise CaseCompileError("Compiled GENKEY thermal model disagrees with CaseSpec.")
    expected_boundaries = tuple(sorted(
        (node["label"], float(_number(node["pressure_pa"])), float(_number(node["temperature_c"])))
        for node in expected["nodes"]
        if node["kind"] not in {"junction", "closed"}
    ))
    if validation.boundaries and validation.boundaries != expected_boundaries:
        raise CaseCompileError("Compiled GENKEY boundary pressure or temperature disagrees with CaseSpec.")
    expected_roughness = tuple(sorted(
        (flowpath["label"], pipe["label"], float(_number(pipe["roughness_m"])))
        for flowpath in expected["flowpaths"]
        for pipe in flowpath["pipes"]
    ))
    if validation.roughness and validation.roughness != expected_roughness:
        raise CaseCompileError("Compiled GENKEY roughness disagrees with CaseSpec.")
    after = file_sha256(owner) if owner is not None else None
    if before != after:
        raise CaseCompileError("Owner source changed during read-only compilation.")
    return CompilationResult(
        compiled,
        hashlib.sha256(compiled).hexdigest(),
        validation,
        edges,
        sections,
        source_mutated=False,
        companion_status=companion_status,
        warnings=companion_warnings,
    )
