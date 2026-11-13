"""Reference-free CaseSpec schema for the app's small dispatch validator."""

from __future__ import annotations

from .case_spec_types import OUTPUT_NAMES
from .case_spec_validation import JsonObject


def _closed(properties: JsonObject, required: list[str]) -> JsonObject:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _bounded(maximum: float, minimum: float = 1e-12) -> JsonObject:
    return {"type": "number", "minimum": minimum, "maximum": maximum}


_TEMPERATURE_C: JsonObject = {"type": "number", "minimum": -273.15, "maximum": 1_500}


def inline_thermal_schema() -> JsonObject:
    """Thermal choice as one closed object; per-model fields are conditionally required."""
    wall = _closed(
        {
            "thickness_m": _bounded(1.0),
            "material": _closed(
                {
                    "conductivity_w_mk": _bounded(1_000),
                    "heat_capacity_j_kgk": _bounded(100_000),
                    "density_kg_m3": _bounded(30_000),
                },
                ["conductivity_w_mk", "heat_capacity_j_kgk", "density_kg_m3"],
            ),
        },
        ["thickness_m", "material"],
    )
    thermal = _closed(
        {
            "model": {"type": "string", "enum": ["adiabatic", "ambient_h_given"]},
            "ambient_temperature_c": _TEMPERATURE_C,
            "outer_heat_transfer_coefficient_w_m2k": _bounded(100_000),
            "wall": wall,
        },
        ["model"],
    )
    thermal["allOf"] = [
        {
            "if": {"properties": {"model": {"const": "adiabatic"}}, "required": ["model"]},
            "then": _closed({"model": {"const": "adiabatic"}}, ["model"]),
        },
        {
            "if": {"properties": {"model": {"const": "ambient_h_given"}}, "required": ["model"]},
            "then": _closed(
                {
                    "model": {"const": "ambient_h_given"},
                    "ambient_temperature_c": _TEMPERATURE_C,
                    "outer_heat_transfer_coefficient_w_m2k": _bounded(100_000),
                    "wall": wall,
                },
                [
                    "model",
                    "ambient_temperature_c",
                    "outer_heat_transfer_coefficient_w_m2k",
                    "wall",
                ],
            ),
        },
    ]
    return thermal


def inline_case_spec_schema() -> JsonObject:
    """Return a closed schema without ``$ref`` or unsupported union keywords."""
    label: JsonObject = {
        "type": "string",
        "minLength": 1,
        "maxLength": 66,
        "pattern": r"^\s*[A-Za-z][A-Za-z0-9_]{0,63}\s*$",
    }
    number: JsonObject = {
        "type": "number",
        "minimum": -10_000_000,
        "maximum": 10_000_000,
    }
    positive: JsonObject = {"type": "number", "minimum": 1e-12}
    point: JsonObject = {
        "type": "array",
        "items": number,
        "minItems": 3,
        "maxItems": 3,
        "description": (
            "[x, y, z] metres; y is elevation (OLGA vertical axis); x and z are horizontal"
        ),
    }
    pipe = _closed(
        {
            "label": label,
            "centerline_m": {
                "type": "array",
                "items": point,
                "minItems": 2,
                "maxItems": 2,
                "description": (
                    "start and end point; a vertical riser changes y only, "
                    "e.g. [[0,0,0],[0,10,0]]"
                ),
            },
            "diameter_m": {**positive, "maximum": 10},
            "roughness_m": {"type": "number", "minimum": 0, "maximum": 0.1},
            "sections": {"type": "integer", "minimum": 1, "maximum": 5_000},
        },
        ["label", "centerline_m", "diameter_m", "roughness_m", "sections"],
    )
    flowpath = _closed(
        {
            "label": label,
            "from": label,
            "to": label,
            "pipes": {"type": "array", "items": pipe, "minItems": 1, "maxItems": 500},
            "initial_void_fraction": {"type": "number", "minimum": 0, "maximum": 1},
        },
        ["label", "from", "to", "pipes"],
    )
    node = _closed(
        {
            "label": label,
            "kind": {"type": "string", "enum": ["source", "sink", "junction", "closed"]},
            "pressure_pa": {**positive, "maximum": 1_000_000_000},
            "temperature_c": _TEMPERATURE_C,
            "gas_fraction": {"type": "number", "minimum": 0, "maximum": 1},
            "total_water_fraction": {"type": "number", "minimum": 0, "maximum": 1},
        },
        ["label", "kind"],
    )
    node["allOf"] = [
        {
            "if": {"properties": {"kind": {"const": kind}}},
            "then": {
                "required": [
                    "pressure_pa",
                    "temperature_c",
                    "gas_fraction",
                    "total_water_fraction",
                ]
            },
        }
        for kind in ("source", "sink")
    ]
    node["allOf"].append({
        "if": {"properties": {"kind": {"const": "closed"}}, "required": ["kind"]},
        "then": _closed(
            {"label": label, "kind": {"const": "closed"}},
            ["label", "kind"],
        ),
    })
    interval = {**positive, "maximum": 31_536_000}
    integration = _closed(
        {
            "end_time_s": interval,
            "trend_interval_s": interval,
            "profile_interval_s": interval,
            "output_interval_s": interval,
            "max_dt_s": interval,
            "steady_state": {"type": "boolean"},
            "dt_start_s": interval,
            "min_dt_s": interval,
        },
        ["end_time_s"],
    )
    fraction: JsonObject = {"type": "number", "minimum": 0, "maximum": 1}
    massflow_point = _closed(
        {
            "time_s": {"type": "number", "minimum": 0, "maximum": 31_536_000},
            "mass_flow_kg_s": {"type": "number", "minimum": 0, "maximum": 1_000_000},
            "temperature_c": _TEMPERATURE_C,
            "gas_fraction": fraction,
            "total_water_fraction": fraction,
        },
        [
            "time_s",
            "mass_flow_kg_s",
            "temperature_c",
            "gas_fraction",
            "total_water_fraction",
        ],
    )
    massflow_source = _closed(
        {
            "label": label,
            "flowpath": label,
            "pipe": label,
            "section": {"type": "integer", "minimum": 1, "maximum": 5_000},
            "time_s": {"type": "number", "minimum": 0, "maximum": 31_536_000},
            "mass_flow_kg_s": {"type": "number", "minimum": 0, "maximum": 1_000_000},
            "temperature_c": _TEMPERATURE_C,
            "gas_fraction": fraction,
            "total_water_fraction": fraction,
            "series": {
                "type": "array",
                "minItems": 2,
                "maxItems": 500,
                "items": massflow_point,
            },
        },
        [
            "label",
            "flowpath",
            "pipe",
            "section",
            "time_s",
            "mass_flow_kg_s",
            "temperature_c",
            "gas_fraction",
            "total_water_fraction",
        ],
    )
    # v3 valve opening timetable; CaseSpec checks increasing times and the first opening.
    valve_schedule: JsonObject = {
        "type": "array",
        "minItems": 2,
        "maxItems": 500,
        "items": _closed(
            {
                "time_s": {"type": "number", "minimum": 0, "maximum": 31_536_000},
                "opening": fraction,
            },
            ["time_s", "opening"],
        ),
    }
    equipment = _closed(
        {
            "kind": {
                "type": "string",
                "minLength": 1,
                "maxLength": 32,
                "pattern": r"^[A-Za-z][A-Za-z0-9_-]{0,31}$",
            },
            "label": label,
            "flowpath": label,
            "pipe": label,
            "position": {"type": "number", "minimum": 0, "maximum": 1},
            "diameter_m": {**positive, "maximum": 10},
            "opening": {"type": "number", "minimum": 0, "maximum": 1},
            "schedule": valve_schedule,
        },
        ["kind", "label"],
    )
    equipment["allOf"] = [
        {
            "if": {"properties": {"kind": {"const": "valve"}}, "required": ["kind"]},
            "then": _closed(
                {
                    "kind": {"const": "valve"},
                    "label": label,
                    "flowpath": label,
                    "pipe": label,
                    "position": {"type": "number", "minimum": 0, "maximum": 1},
                    "diameter_m": {**positive, "maximum": 10},
                    "opening": {"type": "number", "minimum": 0, "maximum": 1},
                    "schedule": valve_schedule,
                },
                ["kind", "label", "flowpath", "pipe", "position", "diameter_m", "opening"],
            ),
        }
    ]
    return _closed(
        {
            # "1" is accepted here only so validation can explain why it cannot be used.
            "version": {"type": "string", "enum": ["1", "2", "3"]},
            "nodes": {"type": "array", "items": node, "minItems": 2, "maxItems": 256},
            "flowpaths": {
                "type": "array",
                "items": flowpath,
                "minItems": 1,
                "maxItems": 512,
            },
            "pvt_reference": {
                "type": "string",
                "minLength": 5,
                "maxLength": 240,
                "pattern": r"^[A-Za-z0-9_][A-Za-z0-9 ._/-]*\.tab$",
            },
            "fluid_label": {
                "type": "string",
                "minLength": 1,
                "maxLength": 66,
                "pattern": r"^\s*[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\s*$",
            },
            "thermal": inline_thermal_schema(),
            "integration": integration,
            "outputs": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [*OUTPUT_NAMES, *(name.lower() for name in OUTPUT_NAMES)],
                },
                "minItems": 1,
                "maxItems": len(OUTPUT_NAMES),
                "uniqueItems": True,
            },
            "massflow_sources": {
                "type": "array",
                "items": massflow_source,
                "maxItems": 32,
            },
            "equipment": {
                "type": "array",
                "items": equipment,
                "minItems": 1,
                "maxItems": 16,
            },
            "trend_positions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": _closed(
                    {
                        "label": label,
                        "pipe": label,
                        "section": {"type": "integer", "minimum": 1, "maximum": 5_000},
                    },
                    ["label", "pipe", "section"],
                ),
            },
            "initial_conditions": _closed(
                {
                    "pressure_pa": {**positive, "maximum": 1_000_000_000},
                    "temperature_c": _TEMPERATURE_C,
                    "void_fraction": fraction,
                },
                ["pressure_pa", "temperature_c", "void_fraction"],
            ),
        },
        [
            "version",
            "nodes",
            "flowpaths",
            "pvt_reference",
            "fluid_label",
            "thermal",
            "integration",
            "outputs",
        ],
    )
