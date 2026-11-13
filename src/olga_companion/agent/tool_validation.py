"""Shared validation and result-bounding rules for the agent tool belt."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from .. import workspace
from .json_schema_validation import SchemaValidationError, validate_json_schema

MAX_RESULT_BYTES: Final = 16384
CASE_ARG_KEY: Final = {
    "genkey_review": "path",
    "genkey_topology": "path",
    "genkey_modify": "path",
    "fluids_consistency": "path",
    "run_detect": "source",
    "run_preview": "source",
    "run_execute": "source",
    "case_edit_plan": "source",
}


class ToolError(ValueError):
    """A tool call was malformed or refused."""


class ToolFailedError(ToolError):
    """The action ended in a known failed state, so it is certain and safe to call it failed.

    Unlike a bare ToolError, which an entered step must treat as uncertain, this one says the
    outcome is known. It may follow a write, for example a kept file that failed its check.
    """


class ToolRefusedError(ToolFailedError):
    """The action was refused before anything started or changed, so it is safe to call it failed."""


def _validate_series_range(args: dict[str, Any]) -> None:
    selected = args.get("time_range")
    if not isinstance(selected, dict):
        return
    start = selected.get("start")
    end = selected.get("end")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start > end:
        raise ToolError("Invalid time range: start must be less than or equal to end.")


def _validate_compare_lengths(args: dict[str, Any]) -> None:
    files = args.get("files")
    labels = args.get("labels")
    if isinstance(files, list) and isinstance(labels, list) and len(files) != len(labels):
        raise ToolError("Invalid report comparison: labels must match the number of files.")


def _validate_export_selection(args: dict[str, Any]) -> None:
    _validate_series_range(args)
    view_fields = {
        "position",
        "value_unit",
        "time_unit",
        "quantity_kind",
        "time_range",
        "timestep",
    }
    selected_view = bool(view_fields.intersection(args)) or args.get("format") == "pdf"
    if not selected_view:
        return
    # A .ppl profile picks its time with timestep alone; it has no position.
    if (
        str(args.get("path", "")).casefold().endswith(".ppl")
        and view_fields.intersection(args) == {"timestep"}
        and args.get("format") != "pdf"
    ):
        return
    if not args.get("position"):
        raise ToolError("A selected series export or PDF requires position.")
    variables = args.get("variables")
    if not isinstance(variables, list) or len(variables) != 1:
        raise ToolError("A selected series export requires exactly one variable.")


def _validate_case_edit_plan(args: dict[str, Any]) -> None:
    source_pair = bool(args.get("source")) and bool(args.get("source_hash"))
    spec_pair = isinstance(args.get("spec"), dict) and bool(args.get("spec_hash"))
    draft = bool(args.get("draft_id"))
    if [source_pair, spec_pair, draft].count(True) != 1:
        raise ToolError(
            "case_edit_plan requires exactly one of a source/hash pair, a spec/hash pair or a draft_id."
        )
    if draft and not args.get("destination_rel"):
        raise ToolError("case_edit_plan with draft_id requires destination_rel, a new .genkey file.")
    for operation in args.get("operations", []):
        if (
            isinstance(operation, dict)
            and operation.get("op") == "set_pipe_geometry"
            and operation.get("diameter_m") is None
            and operation.get("elevation_offset_m") is None
        ):
            raise ToolError("set_pipe_geometry requires at least one geometry change.")


_SEMANTIC_VALIDATORS: Final = {
    "case_edit_plan": _validate_case_edit_plan,
    "results_series": _validate_series_range,
    "report_compare": _validate_compare_lengths,
    "results_csv": _validate_export_selection,
    "results_plot": _validate_export_selection,
}
_SIDE_EFFECT_TOOLS: Final = {
    "action_plan",
    "case_publish",
    "genkey_save",
    "fluids_draft_mfl",
    "fluids_generate_tab",
    "fluids_starter_tab",
    "multiflash_open",
    "run_execute",
    "run_cancel",
    "sweep_execute",
    "sweep_cancel",
}
_TIMEOUT_TOOLS: Final = {"run_preview", "run_execute", "parametric_sweep"}


def validate_tool_arguments(
    name: str,
    args: dict[str, Any],
    parameters: dict[str, Any],
) -> None:
    """Validate one untrusted model call before its handler is invoked."""
    dispatch_schema = (
        {**parameters, "required": []}
        if name in _SIDE_EFFECT_TOOLS
        else parameters
    )
    try:
        validate_json_schema(dispatch_schema, args)
    except SchemaValidationError as exc:
        if name in _TIMEOUT_TOOLS and exc.path == "$.timeout_s":
            raise ToolError("timeout_s must be an integer between 1 and 604800") from exc
        raise ToolError(f"Invalid arguments for {name!r}: {exc}") from exc
    semantic = _SEMANTIC_VALIDATORS.get(name)
    if semantic is not None:
        semantic(args)


def validate_tool_result(
    name: str,
    result: dict[str, Any],
    response_schema: dict[str, Any] | None,
) -> None:
    """Reject a malformed typed producer response before transcript capping."""
    if response_schema is None:
        return
    try:
        validate_json_schema(response_schema, result)
    except SchemaValidationError as exc:
        raise ToolError(f"Invalid result for {name!r}: {exc}") from exc
    _validate_result_identities(name, result)


def _validate_result_identities(name: str, result: dict[str, Any]) -> None:
    """Reuse the producer's canonical opaque-ID grammar at the output boundary."""
    from .result_tools import canonical_result_id

    pairs: list[tuple[str | None, Any]] = []
    if name == "results_inventory":
        pairs.extend(
            (str(item.get("result_id")), item.get("lineage"))
            for item in result.get("results", [])
            if isinstance(item, dict)
        )
    elif name == "results_series":
        pairs.append((str(result.get("result_id")), result.get("lineage")))
    elif name in {"results_csv", "results_plot", "report_figure"}:
        pairs.append((None, result.get("lineage")))
    for result_id, lineage in pairs:
        if not isinstance(lineage, dict):
            continue
        source_id = canonical_result_id(str(lineage.get("source_id")))
        source_kind = str(lineage.get("source_kind"))
        if source_kind != source_id.partition(":")[0]:
            raise ToolError("Invalid result identity: lineage source kind does not match.")
        if result_id is not None and canonical_result_id(result_id) != source_id:
            raise ToolError("Invalid result identity: result_id and lineage source_id differ.")


@dataclass(frozen=True, slots=True)
class PathBindings:
    """Facade-resolved path and active-case seams used by extracted handlers."""

    input_file: Callable[[str, set[str]], str]
    result_file: Callable[[str], str]
    set_active_case: Callable[[str | None], str | None]


def apply_active_default(
    name: str,
    args: dict[str, Any],
    case_arg_key: Mapping[str, str] = CASE_ARG_KEY,
) -> dict[str, Any]:
    """Fill an omitted case path from the active workspace case."""
    if name == "case_edit_plan" and ("spec" in args or "draft_id" in args):
        return args
    key = case_arg_key.get(name)
    if key and not args.get(key):
        active = workspace.active_path()
        if active:
            return {**args, key: active}
    return args


def set_active_case(path: str | None) -> str | None:
    """Best-effort record of the case most recently touched by a tool.

    A refused path leaves the previous active case in place and returns the reason.
    """
    if not path:
        return None
    try:
        workspace.set_active_path(path)
    except (OSError, workspace.WorkspaceError) as exc:
        return str(exc)
    return None


def input_file(value: str, suffixes: set[str]) -> str:
    """Resolve an allowlisted input file inside a trusted root."""
    return str(workspace.resolve_input_file(value, suffixes))


def result_file(value: str) -> str:
    """Resolve a result file inside the workspace or result sandbox."""
    return str(workspace.resolve_result(value))


DEFAULT_PATH_BINDINGS: Final = PathBindings(input_file, result_file, set_active_case)


# Lists a producer already caps; the generic cap keeps them whole.
# The endpoints summary caps "ends" at _MAX_ENDS (100).
LIST_CAP_BY_KEY = {"ends": 100}


def truncate_value(value: Any, cap: int, list_cap: int = 50) -> Any:
    """Recursively cap long strings while preserving payload shape.

    Lists are cut to ``list_cap`` items, except keys a producer already
    caps (see ``LIST_CAP_BY_KEY``), which pass through whole.
    """
    if isinstance(value, str):
        if len(value) <= cap:
            return value
        return value[:cap] + (
            f"\n…[{len(value) - cap} more chars truncated — "
            "read the artifact for the full report]"
        )
    if isinstance(value, dict):
        return {
            key: truncate_value(item, cap, LIST_CAP_BY_KEY.get(key, list_cap))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [truncate_value(item, cap, list_cap) for item in value[:list_cap]]
    return value


def cap(
    payload: dict[str, Any],
    max_result_bytes: int = MAX_RESULT_BYTES,
    truncate: Callable[[Any, int], Any] = truncate_value,
) -> dict[str, Any]:
    """Bound serialized tool results without hiding decision-bearing fields."""
    if (
        isinstance(payload, dict)
        and "nodes" in payload
        and "edges" in payload
        and "counts" in payload
    ):
        return payload
    if len(json.dumps(payload, default=str)) <= max_result_bytes:
        return payload
    for string_cap in (4000, 2000, 800, 200):
        trimmed = truncate(payload, string_cap)
        if len(json.dumps(trimmed, default=str)) <= max_result_bytes:
            if isinstance(trimmed, dict):
                trimmed["_truncated"] = True
            return trimmed
    scalars = (
        {
            key: value
            for key, value in payload.items()
            if isinstance(value, (bool, int, float))
        }
        if isinstance(payload, dict)
        else {}
    )
    return {
        **scalars,
        "truncated": True,
        "note": (
            f"Result exceeded {max_result_bytes} bytes; only scalar fields kept. "
            "Read the artifact for details."
        ),
        "keys": sorted(payload) if isinstance(payload, dict) else None,
    }
