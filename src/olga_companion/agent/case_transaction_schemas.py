"""Closed tool-input contracts for atomic case edit and publish operations."""

from __future__ import annotations

from typing import Any, Final

from ..case_spec_dispatch_schema import inline_thermal_schema
from ..case_spec_types import OUTPUT_NAMES
from .case_tool_schemas import CASE_SPEC_INLINE_SCHEMA
from .pipe_table_schemas import DRAFT_ID

def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


_TOKEN: Final = {
    "type": "string",
    "minLength": 1,
    "maxLength": 64,
    "pattern": r"^[A-Za-z][A-Za-z0-9_]*$",
}
_HASH: Final = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_PATH: Final = {"type": "string", "minLength": 1, "maxLength": 4096}
DESTINATION_RULE: Final = (
    "destination_rel is relative to the workspace root. "
    "To save beside the active case, use the active case's workspace-relative folder "
    "plus the new file name. Use only the file name when the active case sits directly in the root."
)
_DESTINATION: Final = {**_PATH, "description": DESTINATION_RULE}
_DRAFT: Final = {
    **DRAFT_ID,
    "description": "Plans a new case from a pipe_table_import draft; never rebuild its spec by hand.",
}
_OPERATION: Final = _object(
    {
        "op": {
            "type": "string",
            "enum": [
                "set_integration",
                "set_pipe_geometry",
                "set_pipe_sections",
                "set_boundary_pressure",
                "set_boundary_temperature",
                "set_pipe_roughness",
                "set_thermal",
                "set_fluid",
                "set_outputs",
                "rename_node",
                "set_source_massflow",
                "set_valve_opening",
            ],
        },
        "end_time_s": {"type": "number", "minimum": 1e-12, "maximum": 31_536_000},
        "flowpath": _TOKEN,
        "pipe": _TOKEN,
        "diameter_m": {"type": "number", "minimum": 1e-12, "maximum": 10},
        "elevation_offset_m": {"type": "number", "minimum": -10_000_000, "maximum": 10_000_000},
        "sections": {"type": "integer", "minimum": 1, "maximum": 5000},
        "node": _TOKEN,
        "pressure_pa": {"type": "number", "minimum": 1e-12, "maximum": 1_000_000_000},
        "temperature_c": {"type": "number", "minimum": -273.15, "maximum": 1_500},
        "roughness_m": {"type": "number", "minimum": 0, "maximum": 0.1},
        "thermal": inline_thermal_schema(),
        "fluid_label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 66,
            "pattern": r"^\s*[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\s*$",
        },
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
        "new_label": _TOKEN,
        "label": _TOKEN,
        "mass_flow_kg_s": {"type": "number", "minimum": 0, "maximum": 1_000_000},
        "gas_fraction": {"type": "number", "minimum": 0, "maximum": 1},
        "total_water_fraction": {"type": "number", "minimum": 0, "maximum": 1},
        "opening": {"type": "number", "minimum": 0, "maximum": 1},
    },
    ["op"],
)
_OP_FIELDS: Final = {
    "set_integration": ["end_time_s"],
    "set_pipe_geometry": ["flowpath", "pipe", "diameter_m", "elevation_offset_m"],
    "set_pipe_sections": ["flowpath", "pipe", "sections"],
    "set_boundary_pressure": ["node", "pressure_pa"],
    "set_boundary_temperature": ["node", "temperature_c"],
    "set_pipe_roughness": ["flowpath", "pipe", "roughness_m"],
    "set_thermal": ["thermal"],
    "set_fluid": ["fluid_label"],
    "set_outputs": ["outputs"],
    "rename_node": ["node", "new_label"],
    "set_source_massflow": [
        "label",
        "mass_flow_kg_s",
        "temperature_c",
        "gas_fraction",
        "total_water_fraction",
    ],
    "set_valve_opening": ["label", "opening"],
}
_OP_REQUIRED: Final = {
    **{name: fields for name, fields in _OP_FIELDS.items()},
    "set_pipe_geometry": ["flowpath", "pipe"],
    "set_source_massflow": ["label", "mass_flow_kg_s"],
}
_OPERATION["allOf"] = [{
    "if": {"properties": {"op": {"const": op}}, "required": ["op"]},
    "then": _object(
        {"op": {"const": op}, **{field: _OPERATION["properties"][field] for field in fields}},
        ["op", *_OP_REQUIRED[op]],
    ),
} for op, fields in _OP_FIELDS.items()]


def _operations(min_items: int) -> dict[str, Any]:
    return {
        "type": "array",
        "items": _OPERATION,
        "minItems": min_items,
        "maxItems": 20,
    }


CASE_TRANSACTION_PARAMETER_SCHEMAS: Final = {
    "case_edit_plan": _object(
        {
            "source": _PATH,
            "source_hash": _HASH,
            "spec": CASE_SPEC_INLINE_SCHEMA,
            "spec_hash": _HASH,
            "draft_id": _DRAFT,
            "destination_rel": _DESTINATION,
            # Empty arrays reach allOf. Owner mode restates minItems 1.
            "operations": _operations(0),
        },
        ["operations"],
    ),
    "case_publish": _object(
        {
            "transaction_id": {
                "type": "string",
                "minLength": 16,
                "maxLength": 128,
                "pattern": r"^[A-Za-z0-9_-]+$",
            },
            "source_hash": _HASH,
            "compiled_hash": _HASH,
            "destination_rel": _DESTINATION,
            "context_generation": {"type": "integer", "minimum": 0},
            "approval_token": {"type": "string", "minLength": 1, "maxLength": 4096},
            "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 256},
        },
        [
            "transaction_id",
            "source_hash",
            "compiled_hash",
            "destination_rel",
            "context_generation",
            "approval_token",
            "idempotency_key",
        ],
    ),
}
CASE_TRANSACTION_PARAMETER_SCHEMAS["case_edit_plan"]["allOf"] = [
    {
        "if": {"required": ["source"]},
        "then": _object(
            {
                "source": _PATH,
                "source_hash": _HASH,
                "destination_rel": _DESTINATION,
                "operations": _operations(1),
            },
            ["source", "source_hash", "operations"],
        ),
    },
    {
        "if": {"required": ["spec"]},
        "then": _object(
            {
                "spec": CASE_SPEC_INLINE_SCHEMA,
                "spec_hash": _HASH,
                "destination_rel": _DESTINATION,
                "operations": _operations(0),
            },
            ["spec", "spec_hash", "operations"],
        ),
    },
    {
        # A draft_id of any real length (minLength 1) fails maxLength 0, so this clause
        # keeps meaning "no operations and no draft": the spec-free copy of a new case.
        "if": {
            "properties": {"operations": {"maxItems": 0}, "draft_id": {"maxLength": 0}},
            "required": ["operations"],
        },
        "then": _object(
            {
                "spec": CASE_SPEC_INLINE_SCHEMA,
                "spec_hash": _HASH,
                "destination_rel": _DESTINATION,
                "operations": _operations(0),
            },
            ["spec", "spec_hash", "destination_rel", "operations"],
        ),
    },
    {
        "if": {"properties": {"draft_id": {"minLength": 1}}, "required": ["draft_id"]},
        # The root properties already type these fields; here only the allowed set matters.
        "then": _object(
            {
                "draft_id": {"type": "string"},
                "destination_rel": {"type": "string"},
                "operations": {"type": "array"},
            },
            ["draft_id", "destination_rel", "operations"],
        ),
    },
]
