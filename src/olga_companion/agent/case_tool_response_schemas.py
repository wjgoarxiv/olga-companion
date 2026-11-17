"""Typed public result contracts for read-only CaseSpec planning tools."""

from __future__ import annotations

from typing import Any, Final

from ..case_spec_types import OUTPUT_NAMES
from .case_tool_schemas import CASE_SPEC_INLINE_SCHEMA


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


_ISSUE: Final = _object(
    {
        "code": {"type": "string", "minLength": 1},
        "field": {"type": "string", "minLength": 1},
        "message": {"type": "string", "minLength": 1},
        "guidance": {"type": "string", "minLength": 1},
    },
    ["code", "field", "message", "guidance"],
)
_JUNCTION_CAPABILITY: Final = _object(
    {
        "kind": {"const": "star_split_or_merge"},
        "min_flowterms": {"const": 2},
        "max_flowterms": {"const": 6},
        "min_total_degree": {"const": 3},
        "max_total_degree": {"const": 7},
    },
    ["kind", "min_flowterms", "max_flowterms", "min_total_degree", "max_total_degree"],
)
_CAPABILITIES: Final = _object(
    {
        "version": {"const": "2"},
        "arbitrary_branched_topology": {"const": True},
        "acyclic": {"const": True},
        "node_kinds": {
            "type": "array",
            "items": {"type": "string", "enum": ["source", "sink", "junction", "closed"]},
            "minItems": 4,
            "maxItems": 4,
            "uniqueItems": True,
        },
        "junction": _JUNCTION_CAPABILITY,
        "boundary_fields": _object(
            {
                "source": {
                    "type": "array",
                    "items": {
                        "enum": [
                            "pressure_pa",
                            "temperature_c",
                            "gas_fraction",
                            "total_water_fraction",
                        ]
                    },
                },
                "sink": {
                    "type": "array",
                    "items": {
                        "enum": [
                            "pressure_pa",
                            "temperature_c",
                            "gas_fraction",
                            "total_water_fraction",
                        ]
                    },
                },
                "junction": {"type": "array", "maxItems": 0},
                "closed": {"type": "array", "maxItems": 0},
            },
            ["source", "sink", "junction", "closed"],
        ),
        "pipe_fields": {"type": "array", "items": {"type": "string"}},
        "thermal_models": {"type": "object"},
        "coordinate_axes": _object(
            {
                "vertical": {"const": "y"},
                "horizontal": {"type": "array", "items": {"enum": ["x", "z"]}},
                "note": {"type": "string"},
            },
            ["vertical", "horizontal", "note"],
        ),
        "units": _object(
            {
                "coordinate": {"const": "m"},
                "diameter": {"const": "m"},
                "roughness": {"const": "m"},
                "pressure": {"const": "Pa"},
                "temperature": {"const": "C"},
                "time": {"const": "s"},
            },
            ["coordinate", "diameter", "roughness", "pressure", "temperature", "time"],
        ),
        "outputs": {
            "type": "array",
            "items": {"type": "string", "enum": list(OUTPUT_NAMES)},
            "minItems": len(OUTPUT_NAMES),
            "maxItems": len(OUTPUT_NAMES),
            "uniqueItems": True,
        },
        "pvt_reference": {"type": "string", "minLength": 1},
        "fluid_label": {"type": "string", "minLength": 1},
        "user_must_state": {"type": "array", "items": {"type": "string"}},
        "fixed_solver_controls": {"type": "object"},
        "raw_genkey": {"const": False},
        "writes": {"const": False},
    },
    [
        "version",
        "arbitrary_branched_topology",
        "acyclic",
        "node_kinds",
        "junction",
        "boundary_fields",
        "pipe_fields",
        "thermal_models",
        "coordinate_axes",
        "units",
        "outputs",
        "pvt_reference",
        "fluid_label",
        "user_must_state",
        "fixed_solver_controls",
        "raw_genkey",
        "writes",
    ],
)
_BASE_PROPERTIES: Final = {
    "valid": {"type": "boolean"},
    "publishable": {"type": "boolean"},
    "version": {"type": "string", "enum": ["2", "3"]},
    "normalized": {**CASE_SPEC_INLINE_SCHEMA, "type": ["object", "null"]},
    "spec_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "capabilities": _CAPABILITIES,
    "errors": {"type": "array", "items": _ISSUE},
    "warnings": {"type": "array", "items": _ISSUE},
}
_BASE_REQUIRED: Final = [
    "valid",
    "publishable",
    "version",
    "normalized",
    "capabilities",
    "errors",
    "warnings",
]
CASE_SPEC_VALIDATE_RESPONSE_SCHEMA: Final = _object(_BASE_PROPERTIES, _BASE_REQUIRED)
CASE_SPEC_VALIDATE_RESPONSE_SCHEMA["allOf"] = [{
    "if": {"properties": {"valid": {"const": True}}, "required": ["valid"]},
    "then": {"required": ["spec_hash"]},
}]

_NODE: Final = _object(
    {
        "label": {"type": "string"},
        "kind": {"type": "string", "enum": ["source", "sink", "junction", "closed"]},
    },
    ["label", "kind"],
)
_EDGE: Final = _object(
    {"from": {"type": "string"}, "to": {"type": "string"}, "flowpath": {"type": "string"}},
    ["from", "to", "flowpath"],
)
_POINT: Final = {
    "type": "array",
    "items": {"type": "number", "minimum": -10_000_000, "maximum": 10_000_000},
    "minItems": 3,
    "maxItems": 3,
}
_CENTERLINE: Final = {
    "type": "array",
    "items": _POINT,
    "minItems": 2,
    "maxItems": 2,
}
_GEOMETRY: Final = _object(
    {
        "flowpath": {"type": "string"},
        "pipe": {"type": "string"},
        "centerline_m": _CENTERLINE,
        "diameter_m": {"type": "number"},
        "sections": {"type": "integer", "minimum": 1, "maximum": 5000},
    },
    ["flowpath", "pipe", "centerline_m", "diameter_m", "sections"],
)
_COMPILE_PROPERTIES: Final = {
    **_BASE_PROPERTIES,
    "compiled_text": {"type": "string", "minLength": 1, "maxLength": 1_048_576},
    "compiled_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "topology": _object(
        {
            "nodes": {"type": "array", "items": _NODE},
            "edges": {"type": "array", "items": _EDGE},
        },
        ["nodes", "edges"],
    ),
    "geometry": {"type": "array", "items": _GEOMETRY},
    "validation": _object(
        {
            "clean": {"type": "boolean"},
            "parser_clean": {"type": "boolean"},
            "validator_clean": {"type": "boolean"},
            "diagnostics": {"type": "array", "items": {"type": "string"}},
        },
        ["clean", "parser_clean", "validator_clean", "diagnostics"],
    ),
    "section_count": {"type": "integer", "minimum": 1, "maximum": 5000},
    "companion_status": {"enum": ["unverified", "verified"]},
    "source_mutated": {"const": False},
}
_COMPILED_REQUIRED: Final = [
    "spec_hash",
    "compiled_text",
    "compiled_hash",
    "topology",
    "geometry",
    "validation",
    "section_count",
    "companion_status",
    "source_mutated",
]
CASE_SPEC_COMPILE_RESPONSE_SCHEMA: Final = _object(_COMPILE_PROPERTIES, _BASE_REQUIRED)
CASE_SPEC_COMPILE_RESPONSE_SCHEMA["allOf"] = [
    {
        "if": {"properties": {"valid": {"const": True}}, "required": ["valid"]},
        "then": {
            "properties": {"publishable": {"const": False}},
            "required": _COMPILED_REQUIRED,
        },
    }
]

CASE_TOOL_RESPONSE_SCHEMAS: Final = {
    "case_spec_validate": CASE_SPEC_VALIDATE_RESPONSE_SCHEMA,
    "case_spec_compile": CASE_SPEC_COMPILE_RESPONSE_SCHEMA,
}
