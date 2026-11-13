"""Closed provider and public-result schemas for setup and patrol tools."""

from __future__ import annotations

from typing import Any, Final


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


_HASH: Final = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ID: Final = {
    "type": "string",
    "minLength": 8,
    "maxLength": 128,
    "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]+$",
}
_BINDING: Final = _object(
    {
        "kind": {"type": "string", "enum": ["active_case", "transaction"]},
        "transaction_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        "source_sha256": _HASH,
        "compiled_sha256": _HASH,
    },
    ["kind", "source_sha256"],
)
_BINDING["allOf"] = [
    {
        "if": {"properties": {"kind": {"const": "active_case"}}, "required": ["kind"]},
        "then": _object(
            {"kind": {"const": "active_case"}, "source_sha256": _HASH},
            ["kind", "source_sha256"],
        ),
    },
    {
        "if": {"properties": {"kind": {"const": "transaction"}}, "required": ["kind"]},
        "then": _object(
            {
                "kind": {"const": "transaction"},
                "transaction_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                "source_sha256": _HASH,
                "compiled_sha256": _HASH,
            },
            ["kind", "transaction_id", "source_sha256", "compiled_sha256"],
        ),
    },
]

SIMULATION_SETUP_PARAMETER_SCHEMA: Final = _object(
    {
        "binding": _BINDING,
        "integration": _object(
            {"end_time_s": {"type": "integer", "minimum": 1, "maximum": 31_536_000}},
            ["end_time_s"],
        ),
        "outputs": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[A-Z][A-Z0-9_.]{0,31}$"},
            "minItems": 1,
            "maxItems": 32,
            "uniqueItems": True,
        },
        "runtime": _object(
            {"candidate_id": _ID, "runtime_id": _ID},
            ["candidate_id", "runtime_id"],
        ),
        "timeout_s": {"type": "integer", "minimum": 1, "maximum": 604_800},
        "output_target": _object(
            {"relative_dir": {"const": "managed-run-sandbox"}},
            ["relative_dir"],
        ),
        "context_generation": {"type": "integer", "minimum": 0},
    },
    [
        "binding",
        "integration",
        "outputs",
        "runtime",
        "timeout_s",
        "output_target",
        "context_generation",
    ],
)
RUN_PATROL_PARAMETER_SCHEMA: Final = _object(
    {
        "run_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "deadline_s": {"type": "number", "minimum": 1, "maximum": 3600},
        "max_polls": {"type": "integer", "minimum": 1, "maximum": 20},
        "backoff_s": {"type": "number", "minimum": 0, "maximum": 30},
    },
    ["run_id", "deadline_s", "max_polls", "backoff_s"],
)

_SETUP_PROPERTIES: Final = {
    "ready": {"type": "boolean"},
    "setup_hash": _HASH,
    "run_input_sha256": _HASH,
    "selection_id": _ID,
    "context_generation": {"type": "integer", "minimum": 0},
    "reason": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,63}$"},
    "receipt": {"type": "string", "minLength": 1, "maxLength": 1000},
}
SIMULATION_SETUP_RESPONSE_SCHEMA: Final = _object(
    _SETUP_PROPERTIES, ["ready", "setup_hash", "receipt"]
)
SIMULATION_SETUP_RESPONSE_SCHEMA["allOf"] = [{
    "if": {"properties": {"ready": {"const": True}}, "required": ["ready"]},
    "then": {"required": ["run_input_sha256", "selection_id", "context_generation"]},
    "else": {"required": ["reason"]},
}]

_OBSERVATION: Final = _object(
    {
        "state": {"type": "string", "maxLength": 64},
        "elapsed_s": {"type": "number", "minimum": 0},
        "parse_status": {"type": "string", "maxLength": 64},
        "activity_status": {"type": "string", "maxLength": 64},
        "simulation_time_s": {"type": "number", "minimum": 0},
        "step": {"type": "number", "minimum": 0},
        "adaptive_total_steps": {"type": "number", "minimum": 1},
        "step_size_s": {"type": "number", "minimum": 0},
        "vendor_percent": {"type": "number", "minimum": 0, "maximum": 100},
        "fraction": {"type": "number", "minimum": 0, "maximum": 1},
        "phase": {"type": "string", "maxLength": 64},
        "liveness": {"type": "string", "maxLength": 64},
    },
    [],
)
_DIAGNOSIS: Final = _object(
    {
        "ok": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 128},
        "issue": {"type": "string", "maxLength": 400},
        "issue_count": {"type": "integer", "minimum": 0, "maximum": 20},
        "issues": {"type": "array", "items": {"type": "string", "maxLength": 512}, "maxItems": 20},
        "suggestions": {"type": "array", "items": {"type": "string", "maxLength": 512}, "maxItems": 20},
    },
    ["ok"],
)
_PROPOSAL: Final = _object(
    {
        "supported_case_edit": {"type": "boolean"},
        "summary": {"type": "string", "maxLength": 512},
        "requires_fresh_approval": {"const": True},
        "auto_apply": {"const": False},
        "auto_rerun": {"const": False},
    },
    ["summary", "supported_case_edit", "requires_fresh_approval", "auto_apply", "auto_rerun"],
)
RUN_PATROL_RESPONSE_SCHEMA: Final = _object(
    {
        "run_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "terminal": {"type": "boolean"},
        "state": {"type": "string", "maxLength": 64},
        "stop_reason": {"type": "string", "maxLength": 64},
        "polls": {"type": "integer", "minimum": 0, "maximum": 20},
        "elapsed_s": {"type": "number", "minimum": 0},
        "recovered_from_receipt": {"type": "boolean"},
        "observations": {"type": "array", "items": _OBSERVATION, "maxItems": 20},
        "anomaly": {"type": ["string", "null"], "maxLength": 256},
        "diagnosis": {**_DIAGNOSIS, "type": ["object", "null"]},
        "proposal": {**_PROPOSAL, "type": ["object", "null"]},
        "evidence": _object({"tail": {"type": "string", "maxLength": 2000}}, ["tail"]),
        "outputs": {
            "type": "array",
            "items": _object(
                {"name": {"type": "string", "maxLength": 256}, "suffix": {"type": "string", "maxLength": 16}},
                ["name", "suffix"],
            ),
            "maxItems": 50,
        },
        "actions_dispatched": {"type": "array", "maxItems": 0},
    },
    [
        "run_id", "terminal", "state", "stop_reason", "polls", "elapsed_s",
        "recovered_from_receipt", "observations", "anomaly", "diagnosis",
        "proposal", "evidence", "outputs", "actions_dispatched",
    ],
)

SIMULATION_PATROL_PARAMETER_SCHEMAS: Final = {
    "simulation_setup": SIMULATION_SETUP_PARAMETER_SCHEMA,
    "run_patrol": RUN_PATROL_PARAMETER_SCHEMA,
}
SIMULATION_PATROL_RESPONSE_SCHEMAS: Final = {
    "simulation_setup": SIMULATION_SETUP_RESPONSE_SCHEMA,
    "run_patrol": RUN_PATROL_RESPONSE_SCHEMA,
}
