"""Closed public receipts for reviewed case transactions and publication."""

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
_ID: Final = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
_SNAPSHOT: Final = _object(
    {
        "index": {"type": "integer", "minimum": 0, "maximum": 20},
        "hash": _HASH,
        "previous_hash": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
    },
    ["index", "hash", "previous_hash"],
)
_ISSUE: Final = _object(
    {
        "code": {"type": "string", "minLength": 1, "maxLength": 64},
        "message": {"type": "string", "minLength": 1, "maxLength": 512},
        "evidence": {"type": "string", "maxLength": 160},
    },
    ["code", "message", "evidence"],
)
_SEMANTIC_DIFF: Final = _object(
    {
        "path": {"type": "string", "minLength": 1, "maxLength": 256},
        "before": {"type": "string", "maxLength": 512},
        "after": {"type": "string", "maxLength": 512},
    },
    ["path", "before", "after"],
)
_VALIDATION: Final = _object(
    {
        "clean": {"type": "boolean"},
        "parser_clean": {"type": "boolean"},
        "validator_clean": {"type": "boolean"},
        "diagnostics": {
            "type": "array",
            "items": {"type": "string", "maxLength": 512},
            "maxItems": 20,
        },
    },
    ["clean", "parser_clean", "validator_clean", "diagnostics"],
)
_EDIT_PROPERTIES: Final = {
    "transaction_id": _ID,
    "transaction_hash": _HASH,
    "source_hash": _HASH,
    "working_hash": _HASH,
    "compiled_hash": _HASH,
    "context_generation": {"type": "integer", "minimum": 0},
    "source_kind": {"type": "string", "enum": ["case_spec", "source"]},
    "snapshots": {"type": "array", "items": _SNAPSHOT, "minItems": 1, "maxItems": 21},
    "semantic_diff": {"type": "array", "items": _SEMANTIC_DIFF, "maxItems": 20},
    "text_diff": {
        "type": "array",
        "items": {"type": "string", "maxLength": 240},
        "maxItems": 32,
    },
    "diff_truncated": {"type": "boolean"},
    "backup": _object({"available": {"type": "boolean"}, "sha256": _HASH}, ["available", "sha256"]),
    "validation": _VALIDATION,
    "rollback": _object(
        {
            "available": {"type": "boolean"},
            "restore_hash": _HASH,
            "source_unchanged": {"type": "boolean"},
        },
        ["available", "restore_hash", "source_unchanged"],
    ),
    "publishable": {"type": "boolean"},
    "source_mutated": {"const": False},
    "failed_step": {"type": "integer", "minimum": 0, "maximum": 20},
    "errors": {"type": "array", "items": _ISSUE, "minItems": 1, "maxItems": 20},
}
CASE_EDIT_PLAN_RESPONSE_SCHEMA: Final = _object(
    _EDIT_PROPERTIES,
    [
        "transaction_id",
        "source_hash",
        "context_generation",
        "source_kind",
        "snapshots",
        "publishable",
        "source_mutated",
    ],
)
CASE_EDIT_PLAN_RESPONSE_SCHEMA["allOf"] = [
    {
        "if": {"properties": {"publishable": {"const": True}}, "required": ["publishable"]},
        "then": {
            "required": [
                "transaction_hash",
                "working_hash",
                "compiled_hash",
                "semantic_diff",
                "text_diff",
                "diff_truncated",
                "backup",
                "validation",
                "rollback",
            ]
        },
        "else": {"required": ["failed_step", "errors"]},
    }
]

CASE_PUBLISH_RESPONSE_SCHEMA: Final = _object(
    {
        "version": {"const": 1},
        "receipt_id": _HASH,
        "state": {"const": "completed"},
        "transaction_id": _ID,
        "source_hash": _HASH,
        "compiled_hash": _HASH,
        "published_hash": _HASH,
        "backup_hash": _HASH,
        "destination_rel": {"type": "string", "minLength": 1, "maxLength": 512},
        "context_generation": {"type": "integer", "minimum": 0},
    },
    [
        "version",
        "receipt_id",
        "state",
        "transaction_id",
        "source_hash",
        "compiled_hash",
        "published_hash",
        "backup_hash",
        "destination_rel",
        "context_generation",
    ],
)

CASE_TRANSACTION_RESPONSE_SCHEMAS: Final = {
    "case_edit_plan": CASE_EDIT_PLAN_RESPONSE_SCHEMA,
    "case_publish": CASE_PUBLISH_RESPONSE_SCHEMA,
}
