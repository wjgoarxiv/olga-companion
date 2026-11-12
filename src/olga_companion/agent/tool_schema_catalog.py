"""Closed JSON Schema catalog for non-result model tools."""

from __future__ import annotations

import copy
from typing import Any, Final

from .case_transaction_schemas import CASE_TRANSACTION_PARAMETER_SCHEMAS
from .case_tool_schemas import CASE_SPEC_PARAMETER_SCHEMAS
from .pipe_table_schemas import PIPE_TABLE_PARAMETER_SCHEMAS
from .plan_model import MAX_STEPS, OFFERED_KINDS, offered_kinds
from .simulation_patrol_schemas import SIMULATION_PATROL_PARAMETER_SCHEMAS
from .tool_result_schemas import RESULT_PARAMETER_SCHEMAS


def closed_schema(props: dict[str, str], required: list[str]) -> dict[str, Any]:
    """Build a closed compatibility schema for primitive-only callers."""
    properties: dict[str, Any] = {}
    for name, kind in props.items():
        properties[name] = (
            {"type": "array", "items": {"type": "string"}}
            if kind == "array"
            else {"type": kind}
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


_STRING: Final = {"type": "string", "minLength": 1}
_PATH: Final = {"type": "string", "minLength": 1, "maxLength": 4096}
_TOKEN: Final = {"type": "string", "minLength": 1, "maxLength": 128}
_ID: Final = {"type": "string", "minLength": 1, "maxLength": 256}
_TIMEOUT: Final = {"type": "integer", "minimum": 1, "maximum": 604800}
_ENDTIME: Final = {"type": "integer", "minimum": 1, "maximum": 31536000}
_TOPOLOGY: Final = {
    "type": "string",
    "enum": [
        "simple_pipeline",
        "production_well",
        "well_pipeline",
        "subsea_tieback",
        "riser",
        "separator",
    ],
}

_COMPONENT_ITEM: Final = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 128},
        "mole_fraction": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["name", "mole_fraction"],
}

_FLUID_DRAFT_PROPERTIES: Final = {
    "fluid_label": {"type": "string", "minLength": 1, "maxLength": 64},
    "components": {
        "type": "array",
        "items": _COMPONENT_ITEM,
        "minItems": 1,
        "maxItems": 64,
    },
    "model": {"type": "string", "minLength": 1, "maxLength": 64},
    "temperatures": {
        "type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 512,
    },
    "temperature_unit": {
        "type": "string",
        "minLength": 1,
        "maxLength": 16,
        "description": "Temperature unit keyword (mfcmd p.84): one of K, degC, degF, degR (case-insensitive; C means degC).",
    },
    "pressures": {
        "type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 512,
    },
    "pressure_unit": {
        "type": "string",
        "minLength": 1,
        "maxLength": 16,
        "description": "Pressure unit keyword (mfcmd p.84): one of Pa, kPa, Mpa, bar, barg, atm, atmg, psi, psig, mmHg, inwg, at, atg (case-insensitive).",
    },
    "hawater": {"type": "boolean"},
    "mfl_rel": _PATH,
    "tab_rel": _PATH,
}

_FLUID_DRAFT_REQUIRED: Final = [
    "fluid_label", "components", "model", "temperatures", "temperature_unit",
    "pressures", "pressure_unit", "mfl_rel",
]


_CORE_PARAMETER_SCHEMAS: Final = {
    "genkey_create": _object(
        {"topology": _TOPOLOGY, "endtime_s": _ENDTIME, "pvtfile": _PATH},
        ["topology"],
    ),
    "genkey_review": _object({"path": _PATH}, []),
    "genkey_topology": _object({"path": _PATH}, []),
    "genkey_modify": _object(
        {
            "path": _PATH,
            "keyword": _TOKEN,
            "key": _TOKEN,
            "value": {"type": "string", "minLength": 1, "maxLength": 4096},
            "label": _TOKEN,
        },
        ["keyword", "key", "value"],
    ),
    "genkey_diff": _object({"path_a": _PATH, "path_b": _PATH}, ["path_a", "path_b"]),
    "opi_parse": _object({"path": _PATH}, ["path"]),
    "pipe_geometry": _object(
        {
            "path": _PATH,
            "flowpath": _TOKEN,
            "op": {
                "type": "string",
                "enum": ["list_pipes", "sections", "volume", "elevation_profile", "lowest_point"],
            },
        },
        ["flowpath"],
    ),
    "parametric_sweep": _object(
        {
            "base": _PATH,
            "sweep": {"type": "string", "minLength": 1, "maxLength": 8192},
            "strategy": {"type": "string", "enum": ["oat", "cartesian"]},
            "max_cases": {"type": "integer", "minimum": 1, "maximum": 20},
            "timeout_s": _TIMEOUT,
        },
        ["sweep"],
    ),
    "sweep_status": _object({"sweep_id": _ID}, ["sweep_id"]),
    "fluids_inspect_tab": _object({"path": _PATH}, ["path"]),
    "fluids_inspect_mfl": _object({"path": _PATH}, ["path"]),
    "fluids_consistency": _object({"path": _PATH}, []),
    "fluids_draft_preview": _object(_FLUID_DRAFT_PROPERTIES, _FLUID_DRAFT_REQUIRED),
    "fluids_pickup_tab": _object(
        {"path": _PATH, "fluid_label": _TOKEN}, ["path"]
    ),
    "fluids_compare_tab": _object(
        {"reference_rel": _PATH, "candidate_rel": _PATH},
        ["reference_rel", "candidate_rel"],
    ),
    "multiflash_open": _object({"mfl_path": _PATH}, []),
    "diagnose_out": _object({"path": _PATH}, ["path"]),
    "olga_glossary": _object({"term": {"type": "string", "maxLength": 64}}, []),
    "monitor_snapshot": _object({"path": _PATH}, ["path"]),
    "run_detect": _object({"source": _PATH}, []),
    "run_preview": _object({"source": _PATH, "timeout_s": _TIMEOUT}, []),
    "run_status": _object({"run_id": _ID}, ["run_id"]),
}

_APPROVAL: Final = {"type": "string", "minLength": 1, "maxLength": 4096}
_IDEMPOTENCY: Final = {"type": "string", "minLength": 1, "maxLength": 256}
_PLAN_STEP: Final = _object(
    {
        "kind": {"type": "string", "enum": list(OFFERED_KINDS)},
        "args": {"type": "object"},
        "source_from_step": {"type": "integer", "minimum": 1, "maximum": MAX_STEPS},
    },
    ["kind", "args"],
)
_SIDE_EFFECT_PARAMETER_SCHEMAS: Final = {
    "action_plan": _object(
        {"steps": {"type": "array", "items": _PLAN_STEP, "minItems": 1, "maxItems": MAX_STEPS}},
        ["steps"],
    ),
    "fluids_draft_mfl": _object(
        {**_FLUID_DRAFT_PROPERTIES, "approval_token": _APPROVAL, "idempotency_key": _IDEMPOTENCY},
        [*_FLUID_DRAFT_REQUIRED, "approval_token", "idempotency_key"],
    ),
    "fluids_starter_tab": _object(
        {
            "tab_rel": {**_PATH, "description": "New workspace-relative .tab file; it must not exist yet."},
            "approval_token": _APPROVAL,
            "idempotency_key": _IDEMPOTENCY,
        },
        ["tab_rel", "approval_token", "idempotency_key"],
    ),
    "multiflash_open": _object(
        {
            "mfl_path": _PATH,
            "approval_token": _APPROVAL,
            "idempotency_key": _IDEMPOTENCY,
        },
        ["approval_token", "idempotency_key"],
    ),
    "genkey_save": _object(
        {
            "save_rel": _PATH,
            "topology": _TOPOLOGY,
            "endtime_s": _ENDTIME,
            "pvtfile": _PATH,
            "approval_token": _APPROVAL,
            "idempotency_key": _IDEMPOTENCY,
        },
        ["save_rel", "topology", "approval_token", "idempotency_key"],
    ),
    "sweep_execute": _object(
        {
            "sweep_id": _ID,
            "plan_id": _ID,
            "approval_token": _APPROVAL,
            "idempotency_key": _IDEMPOTENCY,
        },
        ["sweep_id", "plan_id", "approval_token", "idempotency_key"],
    ),
    "sweep_cancel": _object(
        {"sweep_id": _ID, "approval_token": _APPROVAL, "idempotency_key": _IDEMPOTENCY},
        ["sweep_id", "approval_token", "idempotency_key"],
    ),
    "run_execute": _object(
        {
            "source": _PATH,
            "timeout_s": _TIMEOUT,
            "selection_id": _ID,
            "approval_token": _APPROVAL,
            "idempotency_key": _IDEMPOTENCY,
        },
        ["selection_id", "approval_token", "idempotency_key"],
    ),
    "run_cancel": _object(
        {"run_id": _ID, "approval_token": _APPROVAL, "idempotency_key": _IDEMPOTENCY},
        ["run_id", "approval_token", "idempotency_key"],
    ),
}

TOOL_PARAMETER_SCHEMAS: Final = {
    **_CORE_PARAMETER_SCHEMAS,
    **CASE_SPEC_PARAMETER_SCHEMAS,
    **CASE_TRANSACTION_PARAMETER_SCHEMAS,
    **PIPE_TABLE_PARAMETER_SCHEMAS,
    **SIMULATION_PATROL_PARAMETER_SCHEMAS,
    **RESULT_PARAMETER_SCHEMAS,
    **_SIDE_EFFECT_PARAMETER_SCHEMAS,
}


_PENDING_TABLE: Final = {
    "type": "string",
    "minLength": 1,
    "maxLength": 4096,
    "description": (
        "Only for a new case that an action_plan saves right after its fluids_generate_tab step: "
        "the workspace-relative .tab that step will create. It must equal the case's pvt_reference "
        "and is checked again when the case is saved."
    ),
}


def action_plan_schema(native_tab: bool) -> dict[str, Any]:
    """The plan schema, naming the table generator as a step kind only in local PVT builds."""
    base = TOOL_PARAMETER_SCHEMAS["action_plan"]
    if not native_tab:
        return base
    plan = copy.deepcopy(base)
    plan["properties"]["steps"]["items"]["properties"]["kind"]["enum"] = list(offered_kinds(True))
    return plan


def case_edit_plan_schema(native_tab: bool) -> dict[str, Any]:
    """The edit-plan schema, accepting a pending table for a new case only in local PVT builds."""
    base = TOOL_PARAMETER_SCHEMAS["case_edit_plan"]
    if not native_tab:
        return base
    plan = copy.deepcopy(base)
    plan["properties"]["pending_table"] = _PENDING_TABLE
    for clause in plan["allOf"]:
        branch = clause["then"]["properties"]
        if "spec" in branch or "draft_id" in branch:
            branch["pending_table"] = _PENDING_TABLE
    return plan


def generate_tab_schema() -> dict[str, Any]:
    """Closed schema of the in-app table generator; the engine lists come from the engine itself."""
    from .. import native_tab

    component = _object(
        {
            "name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "description": f"Engine component name, one of: {', '.join(native_tab.COMPONENTS)}.",
            },
            "mole_fraction": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        ["name", "mole_fraction"],
    )
    grid = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": native_tab.MAX_GRID_POINTS}
    required = [
        "fluid_label", "components", "model", "temperatures", "temperature_unit",
        "pressures", "pressure_unit", "tab_rel",
    ]
    return _object(
        {
            "fluid_label": _FLUID_DRAFT_PROPERTIES["fluid_label"],
            "components": {"type": "array", "items": component, "minItems": 1, "maxItems": len(native_tab.COMPONENTS)},
            "model": {
                "type": "string",
                "minLength": 1,
                "maxLength": 16,
                "description": (
                    f"Equation of state, one of: {', '.join(native_tab.MODELS)}. "
                    "The user chooses it; never pick one for them."
                ),
            },
            "temperatures": {**grid, "description": "Strictly increasing temperature grid in temperature_unit."},
            "temperature_unit": _FLUID_DRAFT_PROPERTIES["temperature_unit"],
            "pressures": {**grid, "description": "Strictly increasing pressure grid in pressure_unit."},
            "pressure_unit": _FLUID_DRAFT_PROPERTIES["pressure_unit"],
            "tab_rel": {**_PATH, "description": "New workspace-relative .tab file; it must not exist yet."},
            "approval_token": _APPROVAL,
            "idempotency_key": _IDEMPOTENCY,
        },
        [*required, "approval_token", "idempotency_key"],
    )


def parameter_schema(name: str) -> dict[str, Any]:
    """The schema of one tool by name, including the flag-gated table generator."""
    if name == "fluids_generate_tab":
        return generate_tab_schema()
    return TOOL_PARAMETER_SCHEMAS[name]
