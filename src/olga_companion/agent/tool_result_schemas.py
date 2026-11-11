"""Result, report, evaluation, and artifact JSON Schema contracts."""

from __future__ import annotations

from typing import Any, Final


def _object(
    properties: dict[str, Any],
    required: list[str],
    *,
    all_of: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }
    if all_of:
        schema["allOf"] = all_of
    return schema


_STRING: Final = {"type": "string", "minLength": 1}
_PATH: Final = {"type": "string", "minLength": 1, "maxLength": 4096}
_TOKEN: Final = {"type": "string", "minLength": 1, "maxLength": 128}
_STRING_LIST: Final = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
    "minItems": 1,
    "maxItems": 32,
}
_VARIABLE_LIST: Final = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 1,
    "maxItems": 32,
}
_TIME_RANGE: Final = _object(
    {
        "start": {"type": "number", "minimum": 0},
        "end": {"type": "number", "minimum": 0},
    },
    ["start", "end"],
)
_VIEW_SELECTION: Final = {
    "position": {"type": "string", "minLength": 1, "maxLength": 512},
    "value_unit": {"type": "string", "minLength": 1, "maxLength": 64},
    "time_unit": {"type": "string", "minLength": 1, "maxLength": 64},
    "quantity_kind": {"type": "string", "enum": ["point", "delta"]},
    "time_range": _TIME_RANGE,
}
_CRITERION_PARAMS: Final = _object(
    {
        "ppl": _PATH,
        "genkey": _PATH,
        "flowpath": _TOKEN,
        "pipe": _TOKEN,
        "max_litres": {"type": "number", "minimum": 0},
        "branch": _TOKEN,
        "timestep": {"type": "number", "minimum": 0},
        "max_slug_count": {"type": "number", "minimum": 0},
        "file": _PATH,
        "hydrate_temp": {"type": "number"},
        "wax_temp": {"type": "number"},
    },
    [],
)
_CRITERION: Final = _object(
    {
        "kind": {"type": "string", "enum": ["liqc", "slugging", "wax_hydrate"]},
        "params": _CRITERION_PARAMS,
    },
    ["kind", "params"],
    all_of=[
        {
            "if": {"properties": {"kind": {"const": "liqc"}}, "required": ["kind"]},
            "then": {
                "properties": {
                    "params": {
                        "required": ["ppl", "genkey", "flowpath", "pipe", "max_litres"]
                    }
                }
            },
        },
        {
            "if": {"properties": {"kind": {"const": "slugging"}}, "required": ["kind"]},
            "then": {"properties": {"params": {"required": ["ppl", "branch", "max_slug_count"]}}},
        },
        {
            "if": {"properties": {"kind": {"const": "wax_hydrate"}}, "required": ["kind"]},
            "then": {
                "properties": {
                    "params": {"required": ["file", "branch", "hydrate_temp", "wax_temp"]}
                }
            },
        },
    ],
)

RESULT_PARAMETER_SCHEMAS: Final = {
    "results_inventory": _object(
        {
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        [],
    ),
    "results_series": _object(
        {
            "result_id": {"type": "string", "minLength": 1, "maxLength": 4096},
            "variable": _TOKEN,
            "position": {"type": "string", "minLength": 1, "maxLength": 512},
            "value_unit": {"type": "string", "minLength": 1, "maxLength": 64},
            "time_unit": {"type": "string", "minLength": 1, "maxLength": 64},
            "quantity_kind": {"type": "string", "enum": ["point", "delta"]},
            "time_range": _TIME_RANGE,
            "offset": {"type": "integer", "minimum": 0},
            "row_limit": {"type": "integer", "minimum": 1, "maximum": 5000},
            "truncation": {"type": "string", "enum": ["head", "tail", "uniform"]},
        },
        ["result_id", "variable"],
    ),
    "results_profile": _object(
        {
            "result_id": {"type": "string", "minLength": 1, "maxLength": 4096},
            "variable": _TOKEN,
            "branch": _TOKEN,
            "timestep": {"type": "number", "minimum": 0},
        },
        ["result_id", "variable", "branch"],
    ),
    "results_load": _object({"path": _PATH}, ["path"]),
    "results_csv": _object(
        {
            "path": _PATH,
            "variables": _VARIABLE_LIST,
            "branch": _TOKEN,
            **_VIEW_SELECTION,
            "timestep": {"type": "number", "minimum": 0},
        },
        ["path", "variables"],
    ),
    "results_plot": _object(
        {
            "path": _PATH,
            "variables": _VARIABLE_LIST,
            "branch": _TOKEN,
            **_VIEW_SELECTION,
            "format": {"type": "string", "enum": ["png", "pdf"]},
            "timestep": {"type": "number", "minimum": 0},
        },
        ["path", "variables"],
    ),
    "evaluate": _object(
        {"criteria": {"type": "array", "items": _CRITERION, "minItems": 1, "maxItems": 16}},
        ["criteria"],
    ),
    "report_markdown": _object(
        {
            "genkey": _PATH,
            "results": _PATH,
            "ppl": _PATH,
            "criterion": {"type": "number", "minimum": 0},
            "flowpath": _TOKEN,
            "pipe": _TOKEN,
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["criterion"],
                    "properties": {
                        "criterion": {"type": "string", "minLength": 1},
                        "status": {"type": "string"},
                        "verdict": {"type": "string"},
                        "missing": {"type": "array", "items": {"type": "string"}},
                        "values": {},
                        "measured": {},
                        "citations": {},
                        "source_file": {"type": "string"},
                        "source_sha256": {"type": "string"},
                        "source_mutated": {"type": "boolean"},
                        "variables": {"type": "array", "items": {"type": "string"}},
                        "timestep": {},
                        "mapping": {"type": "object"},
                        "formula": {"type": "string"},
                        "threshold": {"type": "object"},
                        "command": {"type": "object"},
                    },
                },
            },
            "figures": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 4096},
            },
        },
        ["genkey"],
        all_of=[
            {
                "if": {"required": ["criterion"]},
                "then": {"required": ["ppl", "flowpath", "pipe"]},
            }
        ],
    ),
    "report_figure": _object(
        {
            "kind": {"type": "string", "enum": ["hol-profile", "liqc-timeseries"]},
            "file": _PATH,
            "branch": _TOKEN,
            "criterion": {"type": "number", "minimum": 0},
            "timestep": {"type": "number", "minimum": 0},
        },
        ["kind", "file", "branch"],
    ),
    "report_compare": _object(
        {
            "files": {"type": "array", "items": _PATH, "minItems": 2, "maxItems": 8},
            "labels": {"type": "array", "items": _TOKEN, "minItems": 2, "maxItems": 8},
            "variables": _STRING_LIST,
            "branch": _TOKEN,
            "timestep": {"type": "number", "minimum": 0},
        },
        ["files"],
    ),
}
