"""Closed tool-input contracts for importing a pipe table into a private case draft.

The drafts are referenced by id only; the CaseSpec schema is never embedded here.
"""

from __future__ import annotations

from typing import Any, Final

from ..case_spec_dispatch_schema import inline_thermal_schema


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


DRAFT_ID: Final = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
_SECTION: Final = {"type": "number", "minimum": 1e-6, "maximum": 100_000}
_RATIO: Final = {"type": "number", "minimum": 1.1, "maximum": 4}
_END_TIME: Final = {"type": "number", "minimum": 1e-12, "maximum": 31_536_000}
_NAME: Final = {"type": "string", "minLength": 1, "maxLength": 128}
_MAX_OPS: Final = 20

_OP: Final = _object(
    {
        "op": {
            "type": "string",
            "enum": ["resegment", "set_valve_schedule", "set_boundary", "set_fluid", "set_thermal", "set_end_time"],
        },
        "max_section_m": _SECTION,
        "max_ratio": _RATIO,
        "pvt_reference": {"type": "string", "minLength": 1, "maxLength": 4096},
        "fluid_label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 66,
            "pattern": r"^\s*[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\s*$",
        },
        "thermal": inline_thermal_schema(),
        "valve": {**_NAME, "description": "Valve name or label such as V_001."},
        "schedule": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": _object(
                {
                    "time_s": {"type": "number", "minimum": 0, "maximum": 31_536_000},
                    "opening": {"type": "number", "minimum": 0, "maximum": 1},
                },
                ["time_s", "opening"],
            ),
        },
        "node": {**_NAME, "description": "Boundary node name from the table, or its label."},
        "pressure_pa": {"type": "number", "minimum": 1e-12, "maximum": 1_000_000_000},
        "temperature_c": {"type": "number", "minimum": -273.15, "maximum": 1_500},
        "end_time_s": _END_TIME,
    },
    ["op"],
)

PIPE_TABLE_PARAMETER_SCHEMAS: Final = {
    "pipe_table_import": _object(
        {
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "column_map": {
                "type": "object",
                "maxProperties": 40,
                "additionalProperties": {"type": "string"},
                "description": "Header -> template.",
            },
            "sheet": {"type": "string", "minLength": 1, "maxLength": 128},
            "unit_length": {"type": "string", "enum": ["m", "cm", "mm"]},
            "layout": {"type": "string", "enum": ["endpoints"]},
            "vertical_axis": {"type": "string", "enum": ["y", "z"]},
            "roughness_m": {"type": "number", "minimum": 0, "maximum": 0.1},
            "segmentation": _object({"max_section_m": _SECTION, "max_ratio": _RATIO}, []),
            "pvt_reference": {"type": "string", "minLength": 1, "maxLength": 4096},
            "fluid_label": {
                "type": "string",
                "minLength": 1,
                "maxLength": 66,
                "pattern": r"^\s*[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\s*$",
            },
            "thermal": inline_thermal_schema(),
            "end_time_s": _END_TIME,
            "max_dt_s": {"type": "number", "minimum": 1e-06},
            "initial_conditions": _object(
                {
                    "pressure_pa": {"type": "number", "minimum": 1e-12, "maximum": 1_000_000_000},
                    "temperature_c": {"type": "number", "minimum": -273.15, "maximum": 1_500},
                },
                [],
            ),
        },
        ["path", "pvt_reference", "fluid_label", "thermal", "end_time_s"],
    ),
    "case_draft_review": _object(
        {"draft_id": DRAFT_ID, "page": {"type": "integer", "minimum": 1, "maximum": 100_000}},
        ["draft_id"],
    ),
    "case_draft_edit": _object(
        {
            "draft_id": DRAFT_ID,
            "revision": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
            "ops": {"type": "array", "items": _OP, "minItems": 1, "maxItems": _MAX_OPS},
        },
        ["draft_id", "revision", "ops"],
    ),
}
