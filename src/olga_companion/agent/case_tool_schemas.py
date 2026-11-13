"""Closed model-tool schemas for deterministic CaseSpec v2 planning."""

from __future__ import annotations

from typing import Any, Final

from ..case_spec_dispatch_schema import inline_case_spec_schema


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


CASE_SPEC_INLINE_SCHEMA: Final = inline_case_spec_schema()
CASE_SPEC_PARAMETER_SCHEMAS: Final = {
    "case_spec_validate": _object({"spec": CASE_SPEC_INLINE_SCHEMA}, ["spec"]),
    "case_spec_compile": _object(
        {
            "spec": CASE_SPEC_INLINE_SCHEMA,
            "owner_source": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        ["spec"],
    ),
}
