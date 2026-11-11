"""Opaque artifact and typed result response JSON Schemas."""

from __future__ import annotations

from typing import Any, Final


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


_STRING: Final = {"type": "string", "minLength": 1}
_TOKEN: Final = {"type": "string", "minLength": 1, "maxLength": 128}
_SHA256: Final = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_RESULT_ID: Final = {
    "type": "string",
    "minLength": 3,
    "maxLength": 4096,
    "pattern": (
        r"^(?:workspace|run):"
        r"(?!(?:.*\/)?\.{1,2}(?:\/|$))"
        r"[^\\/:\x00-\x1f]+(?:\/[^\\/:\x00-\x1f]+)*$"
    ),
}
LINEAGE_SCHEMA: Final = _object(
    {
        "source_kind": {"type": "string", "enum": ["workspace", "run"]},
        "source_id": _RESULT_ID,
        "source_sha256": _SHA256,
        "operation": {
            "type": "string",
            "enum": ["results_csv", "results_plot", "report_figure"],
        },
    },
    ["source_kind", "source_id"],
)
ARTIFACT_RECEIPT_SCHEMA: Final = _object(
    {
        "artifact_id": _STRING,
        "kind": {"type": "string", "enum": ["csv", "png", "pdf"]},
        "mime": {"type": "string", "enum": ["text/csv", "image/png", "application/pdf"]},
        "size_bytes": {"type": "integer", "minimum": 0},
        "sha256": _SHA256,
        "suggested_filename": _STRING,
        "lineage": LINEAGE_SCHEMA,
        "workspace_generation": {"type": "integer", "minimum": 0},
        "actions": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["download", "open_in_results", "native_save_as"],
            },
            "minItems": 1,
            "uniqueItems": True,
        },
    },
    [
        "artifact_id",
        "kind",
        "mime",
        "size_bytes",
        "sha256",
        "suggested_filename",
        "lineage",
        "workspace_generation",
        "actions",
    ],
)
NATIVE_SAVE_AS_ACTION_SCHEMA: Final = _object(
    {
        "requires_human_destination": {"const": True},
        "status": {
            "type": "string",
            "enum": ["available", "dialog_open", "saved", "cancelled", "failed"],
        },
        "save_receipt": _object(
            {
                "suggested_filename": _STRING,
                "size_bytes": {"type": "integer", "minimum": 0},
                "sha256": _SHA256,
            },
            ["suggested_filename", "size_bytes", "sha256"],
        ),
    },
    ["requires_human_destination", "status"],
)
_INVENTORY_ITEM: Final = _object(
    {
        "result_id": _RESULT_ID,
        "name": _STRING,
        "kind": {"type": "string", "enum": ["tpl", "ppl"]},
        "source_sha256": _SHA256,
        "lineage": LINEAGE_SCHEMA,
    },
    ["result_id", "name", "kind", "source_sha256", "lineage"],
)
RESULTS_INVENTORY_RESPONSE_SCHEMA: Final = _object(
    {
        "results": {"type": "array", "items": _INVENTORY_ITEM},
        "total_results": {"type": "integer", "minimum": 0},
        "returned_results": {"type": "integer", "minimum": 0},
        "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "truncated": {"type": "boolean"},
        "workspace_generation": {"type": "integer", "minimum": 0},
    },
    [
        "results",
        "total_results",
        "returned_results",
        "offset",
        "limit",
        "truncated",
        "workspace_generation",
    ],
)
RESULTS_SERIES_RESPONSE_SCHEMA: Final = _object(
    {
        "result_id": _RESULT_ID,
        "rows": {
            "type": "array",
            "items": _object(
                {"time": {"type": "number"}, "value": {"type": "number"}},
                ["time", "value"],
            ),
            "maxItems": 5000,
        },
        "variable": _TOKEN,
        "row_limit": {"type": "integer", "minimum": 1, "maximum": 5000},
        "total_rows": {"type": "integer", "minimum": 0},
        "returned_rows": {"type": "integer", "minimum": 0},
        "units": _object(
            {
                "time": {"type": ["string", "null"]},
                "value": {"type": ["string", "null"]},
            },
            ["time", "value"],
        ),
        "position": {"type": ["string", "null"]},
        "time_range": _object(
            {"start": {"type": "number"}, "end": {"type": "number"}},
            ["start", "end"],
        ),
        "source_sha256": _SHA256,
        "truncated": {"type": "boolean"},
        "truncation": {"type": "string", "enum": ["head", "tail", "uniform"]},
        "analysis": _object(
            {
                "scope": {"const": "descriptive"},
                "samples": {"type": "integer", "minimum": 1},
                "start_time": {"type": "number"},
                "end_time": {"type": "number"},
                "minimum": {"type": "number"},
                "maximum": {"type": "number"},
                "mean": {"type": "number"},
                "initial": {"type": "number"},
                "final": {"type": "number"},
                "delta": {"type": "number"},
                "percent_change": {"type": ["number", "null"]},
                "peak_time": {"type": "number"},
                "direction": {
                    "type": "string",
                    "enum": ["stable", "increasing", "decreasing"],
                },
            },
            [],
        ),
        "lineage": LINEAGE_SCHEMA,
    },
    [
        "result_id",
        "rows",
        "variable",
        "row_limit",
        "total_rows",
        "returned_rows",
        "units",
        "position",
        "time_range",
        "source_sha256",
        "truncated",
        "truncation",
        "analysis",
        "lineage",
    ],
)
TOOL_RESPONSE_SCHEMAS: Final = {
    "results_inventory": RESULTS_INVENTORY_RESPONSE_SCHEMA,
    "results_series": RESULTS_SERIES_RESPONSE_SCHEMA,
    "results_csv": ARTIFACT_RECEIPT_SCHEMA,
    "results_plot": ARTIFACT_RECEIPT_SCHEMA,
    "report_figure": ARTIFACT_RECEIPT_SCHEMA,
}
