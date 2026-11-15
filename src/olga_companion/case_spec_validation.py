"""Structured CaseSpec v2 validation results and capability guidance."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TypeAlias, TypedDict

from pydantic_core import ErrorDetails

from .case_spec_types import OUTPUT_NAMES

JsonValue: TypeAlias = (
    str | int | float | bool | None | Sequence["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
_SAFE_EQUIPMENT = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")


class CaseSpecIssue(TypedDict):
    code: str
    field: str
    message: str
    guidance: str


class CaseSpecValidationResult(TypedDict):
    valid: bool
    publishable: bool
    version: str
    normalized: JsonObject | None
    capabilities: JsonObject
    errors: list[CaseSpecIssue]
    warnings: list[CaseSpecIssue]


def capability_matrix() -> JsonObject:
    """Return the honest, side-effect-free v2 capability matrix."""
    return {
        "version": "2",
        "arbitrary_branched_topology": True,
        "acyclic": True,
        "node_kinds": ["source", "sink", "junction", "closed"],
        "junction": {
            "kind": "star_split_or_merge",
            "min_flowterms": 2,
            "max_flowterms": 6,
            "min_total_degree": 3,
            "max_total_degree": 7,
        },
        "boundary_fields": {
            "source": [
                "pressure_pa",
                "temperature_c",
                "gas_fraction",
                "total_water_fraction",
            ],
            "sink": [
                "pressure_pa",
                "temperature_c",
                "gas_fraction",
                "total_water_fraction",
            ],
            "junction": [],
            "closed": [],
        },
        "pipe_fields": ["diameter_m", "roughness_m", "sections", "centerline_m"],
        "thermal_models": {
            "adiabatic": [],
            "ambient_h_given": [
                "ambient_temperature_c",
                "outer_heat_transfer_coefficient_w_m2k",
                "wall.thickness_m",
                "wall.material.conductivity_w_mk",
                "wall.material.heat_capacity_j_kgk",
                "wall.material.density_kg_m3",
            ],
        },
        "coordinate_axes": {
            "vertical": "y",
            "horizontal": ["x", "z"],
            "note": "centerline_m points are [x, y, z]; y is elevation (OLGA is Y-up)",
        },
        "units": {
            "coordinate": "m",
            "diameter": "m",
            "roughness": "m",
            "pressure": "Pa",
            "temperature": "C",
            "time": "s",
        },
        "outputs": list(OUTPUT_NAMES),
        "pvt_reference": "contained workspace-relative .tab identity",
        "fluid_label": "the PVTTABLE LABEL stored inside that .tab file",
        "user_must_state": [
            "fluid label and PVT .tab file",
            "inlet choice: pressure boundary, or a closed end with a mass-flow inlet",
            "sink pressure and temperature",
            "adiabatic or ambient heat exchange, with its wall and ambient values",
            "pipe diameter and roughness",
            "trend, profile and output intervals, and the maximum timestep",
        ],
        "fixed_solver_controls": {
            "options": (
                "STEADYSTATE=ON; steady_state false is refused until initial conditions "
                "are supplied; COMPOSITIONAL=OFF, FLOWMODEL=OLGAHD"
            ),
            "integration": (
                "MINDT=0.001 s unless min_dt_s is set, STARTTIME=0 s, "
                "DTSTART=1 s unless dt_start_s is set; "
                "MAXDT only when max_dt_s is at most end_time_s/10"
            ),
            "output": "omitted intervals use TREND DTPLOT=end_time/60, PROFILE DTPLOT=end_time/4, OUTPUT DTOUT=end_time",
        },
        "raw_genkey": False,
        "writes": False,
    }


def legacy_version_issue(raw: Mapping[str, JsonValue]) -> CaseSpecIssue | None:
    """Explain why a pre-thermal v1 spec cannot be reused instead of upgrading it."""
    if raw.get("version") != "1":
        return None
    return {
        "code": "legacy_version",
        "field": "version",
        "message": "CaseSpec v1 cannot be compiled: it omits fluid and thermal inputs.",
        "guidance": (
            "Ask the user for the fluid label, source/sink temperature, pipe roughness and "
            "the adiabatic or ambient heat-exchange choice, then resubmit as version \"2\". "
            "Do not fill these in yourself."
        ),
    }


def _named_equipment_kind(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    candidate = item.get("kind")
    if isinstance(candidate, str) and _SAFE_EQUIPMENT.fullmatch(candidate):
        return candidate.lower()
    return None


def unsupported_equipment_issue(raw: Mapping[str, JsonValue]) -> CaseSpecIssue | None:
    equipment = raw.get("equipment")
    if equipment is None:
        return None
    if (
        isinstance(equipment, list)
        and equipment
        and all(isinstance(item, dict) and item.get("kind") == "valve" for item in equipment)
    ):
        return None
    kind = "requested"
    if isinstance(equipment, list):
        for item in equipment:
            named = _named_equipment_kind(item)
            if named is not None and named != "valve":
                kind = named
                break
        else:
            first = _named_equipment_kind(equipment[0]) if equipment else None
            if first is not None:
                kind = first
    return {
        "code": "unsupported_equipment",
        "field": "equipment",
        "message": "Equipment is outside CaseSpec v2.",
        "guidance": f"{kind} equipment is not supported; use source, sink, junction, flowpath and pipe constructs.",
    }


def steady_state_off_issue(spec: object) -> CaseSpecIssue | None:
    """Refuse STEADYSTATE=OFF until a spec can actually carry initial conditions."""
    integration = getattr(spec, "integration", None)
    if getattr(integration, "steady_state", None) is not False:
        return None
    dump = spec.model_dump(mode="python") if hasattr(spec, "model_dump") else {}
    supplied = dump.get("initial_conditions") if isinstance(dump, dict) else None
    if supplied not in (None, (), [], {}):
        return None
    return {
        "code": "steady_state_off_requires_initial_conditions",
        "field": "integration.steady_state",
        "message": "STEADYSTATE=OFF needs initial conditions.",
        "guidance": (
            "Leave steady_state unset so STEADYSTATE stays ON, or in version 3 state "
            "initial_conditions (pressure, temperature, void fraction) from the user."
        ),
    }


def _first_mass_flow(source: object) -> float:
    series = getattr(source, "series", None) or ()
    point = series[0] if series else source
    return float(getattr(point, "mass_flow_kg_s"))


def closed_inlet_zero_source_issue(spec: object) -> CaseSpecIssue | None:
    """Refuse a closed inlet whose steady-state preprocessor would start at 0 kg/s."""
    integration = getattr(spec, "integration", None)
    if getattr(integration, "steady_state", None) is False:
        return None
    nodes = {node.label: node for node in getattr(spec, "nodes", ())}
    for flowpath in getattr(spec, "flowpaths", ()):
        inlet = nodes.get(flowpath.from_node)
        if getattr(inlet, "kind", None) != "closed":
            continue
        first_pipe = flowpath.pipes[0].label
        at_inlet = [
            source
            for source in getattr(spec, "massflow_sources", ())
            if source.flowpath == flowpath.label
            and source.pipe == first_pipe
            and source.section == 1
        ]
        if at_inlet and all(_first_mass_flow(source) == 0 for source in at_inlet):
            return {
                "code": "closed_inlet_requires_nonzero_initial_source",
                "field": "massflow_sources",
                "message": (
                    "A closed inlet needs a non-zero mass flow at the first section "
                    "before the steady-state preprocessor can start."
                ),
                "guidance": (
                    "Ask the user for a non-zero first mass-flow value at section 1 "
                    "of the inlet pipe. Do not invent that flow."
                ),
            }
    return None


def invalid_result(errors: list[CaseSpecIssue]) -> CaseSpecValidationResult:
    return {
        "valid": False,
        "publishable": False,
        "version": "2",
        "normalized": None,
        "capabilities": capability_matrix(),
        "errors": errors,
        "warnings": [],
    }


def validation_issue(error: ErrorDetails) -> CaseSpecIssue:
    location = ".".join(str(part) for part in error.get("loc", ())) or "spec"
    code = _issue_code(str(error.get("type", "invalid_spec")), location)
    guidance = {
        "invalid_label": "Use 1-64 uppercase letters, digits or underscores, beginning with a letter.",
        "flowpath_needs_two_sections": (
            "OLGA stops when a flowpath has fewer than 2 sections in total. "
            "Give each flowpath at least 2 sections."
        ),
        "reserved_label": (
            "OLGA stops at start-up when a label is BOTTOM. Use another name such as "
            "LOOP_BOTTOM and ask the user to accept it."
        ),
        "invalid_pvt_reference": "Use a contained workspace-relative .tab identity without dot segments.",
        "unsupported_output": (
            "CaseSpec v2 outputs are " + ", ".join(OUTPUT_NAMES) + "."
        ),
        "invalid_geometry": (
            "Use finite SI-metre geometry, positive diameter and 1-5000 sections. "
            "In centerline_m [x, y, z], y is elevation (OLGA vertical axis); a vertical "
            "riser changes y only, e.g. [[0,0,0],[0,10,0]]."
        ),
        "invalid_boundary": "Source and sink pressure_pa must be finite and positive; temperature_c must be above -273.15 C.",
        "invalid_fluid_label": "Use the PVTTABLE LABEL stored inside the referenced .tab file (letters, digits, _ . -).",
        "invalid_thermal": "Choose adiabatic, or ambient_h_given with the ambient temperature, outer coefficient and a wall.",
        "invalid_roughness": "roughness_m must be a finite value from 0 to 0.1 m, stated by the user.",
        "invalid_integration": "end_time_s must be in (0, 31536000].",
        "max_dt_exceeds_end_fraction": "max_dt_s must be at most one tenth of end_time_s. Leave it unset rather than inventing a larger step.",
        "min_dt_exceeds_dt_start": (
            "min_dt_s must be at most dt_start_s. An omitted min_dt_s is 0.001 s "
            "and an omitted dt_start_s is 1 s."
        ),
        "max_dt_below_min_dt": (
            "max_dt_s must be at least min_dt_s. An omitted min_dt_s is 0.001 s."
        ),
        "steady_state_off_requires_initial_conditions": (
            "Leave steady_state unset so STEADYSTATE stays ON, or in version 3 state "
            "initial_conditions (pressure, temperature, void fraction) from the user."
        ),
        "closed_inlet_requires_nonzero_initial_source": (
            "Ask the user for a non-zero first mass-flow value at section 1 "
            "of the inlet pipe. Do not invent that flow."
        ),
        "source_series_not_increasing": "A mass-flow series needs at least two times, each later than the one before it.",
        "valve_schedule_not_increasing": "A valve schedule needs at least two times, each later than the one before it.",
        "valve_schedule_opening_mismatch": "Set the valve opening to the first opening in its schedule.",
        "unsupported_initial_conditions": "initial_conditions need version 3.",
        "invalid_topology": (
            "A source or closed node starts one flowpath and a sink ends one; a junction "
            "joins one flowpath on one side and two to six on the other. Directed cycles "
            "are refused: build a circulation loop as two parallel flowpaths that both run "
            "from the bottom junction to the top junction. "
            "Check the drawing too: y is elevation, so the top junction sits at a larger y."
        ),
        "initial_conditions_need_steady_state_off": (
            "initial_conditions replace the steady-state pre-processor; set integration.steady_state to false."
        ),
        "v2_item_limit": (
            "Version 2 takes at most 16 valves (equipment) and 32 mass-flow sources; "
            "a larger network needs version 3."
        ),
        "interval_below_min_dt": "trend, profile and output intervals must be at least MINDT.",
        "interval_count_exceeds_limit": "An interval would record more than 100000 samples. Use a wider interval.",
        "closed_node_without_inflow": (
            "Put a mass-flow inlet on the flowpath that meets this closed node. "
            "Do not invent the mass flow."
        ),
        "pressure_boundary_required": (
            "Keep at least one PRESSURE boundary, a source or a sink. "
            "Do not invent its pressure or temperature."
        ),
        "pressure_node_fractions_required": (
            "Ask the user for gas_fraction and total_water_fraction on every "
            "PRESSURE boundary. Do not fill them in."
        ),
    }.get(code, "Correct the named CaseSpec v2 field and retry validation.")
    return {
        "code": code,
        "field": location,
        "message": "CaseSpec validation rejected this field.",
        "guidance": guidance,
    }


def _issue_code(error_type: str, location: str) -> str:
    explicit = {
        "invalid_label",
        "reserved_label",
        "flowpath_needs_two_sections",
        "invalid_pvt_reference",
        "unsupported_output",
        "duplicate_output",
        "duplicate_label",
        "unknown_reference",
        "disconnected_topology",
        "invalid_topology",
        "invalid_geometry",
        "invalid_fluid_label",
        "closed_node_without_inflow",
        "pressure_boundary_required",
        "max_dt_exceeds_end_fraction",
        "min_dt_exceeds_dt_start",
        "max_dt_below_min_dt",
        "steady_state_off_requires_initial_conditions",
        "closed_inlet_requires_nonzero_initial_source",
        "source_series_not_increasing",
        "valve_schedule_not_increasing",
        "valve_schedule_opening_mismatch",
        "v2_item_limit",
        "unsupported_equipment",
        "unsupported_initial_conditions",
        "initial_conditions_need_steady_state_off",
        "interval_below_min_dt",
        "interval_count_exceeds_limit",
    }
    if error_type in explicit:
        return error_type
    if (
        error_type == "missing"
        and "nodes" in location
        and ("gas_fraction" in location or "total_water_fraction" in location)
    ):
        return "pressure_node_fractions_required"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if "pressure_pa" in location or ("temperature_c" in location and "thermal" not in location):
        return "invalid_boundary"
    if "thermal" in location:
        return "invalid_thermal"
    if "roughness_m" in location:
        return "invalid_roughness"
    if "fluid_label" in location:
        return "invalid_fluid_label"
    if any(
        name in location
        for name in (
            "end_time_s",
            "trend_interval_s",
            "profile_interval_s",
            "output_interval_s",
            "max_dt_s",
            "dt_start_s",
            "min_dt_s",
            "steady_state",
        )
    ):
        return "invalid_integration"
    if any(field in location for field in ("diameter_m", "sections", "centerline_m")):
        return "invalid_geometry"
    if "pvt_reference" in location:
        return "invalid_pvt_reference"
    return "invalid_spec"
