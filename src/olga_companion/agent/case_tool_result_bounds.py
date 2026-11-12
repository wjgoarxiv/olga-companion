"""Typed CaseSpec refusals that stay intact under the global tool-result cap."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from .tool_validation import MAX_RESULT_BYTES


def bounded_compile_result(
    planned: Mapping[str, object], result: dict[str, Any]
) -> dict[str, Any]:
    """Return a closed refusal instead of allowing generic shape-breaking truncation."""
    if len(json.dumps(result, default=str).encode("utf-8")) <= MAX_RESULT_BYTES:
        return result
    refusal = {
        "valid": False,
        "publishable": False,
        "version": planned["version"],
        "normalized": None,
        "capabilities": planned["capabilities"],
        "errors": [{
            "code": "result_too_large",
            "field": "spec",
            "message": "The verified compile preview exceeds the bounded Chat result limit.",
            "guidance": "Reduce CaseSpec v2 scope before preview; no case was published.",
        }],
        "warnings": [],
    }
    if len(json.dumps(refusal).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("CaseSpec bounded refusal exceeds the tool-result limit.")
    return cast(dict[str, Any], refusal)
