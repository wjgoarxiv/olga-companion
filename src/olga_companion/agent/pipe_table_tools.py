"""Agent adapters that import a pipe table into a private draft, review it and edit it.

Every tool here writes only the private draft store; none writes the workspace or needs an
approval. A draft keeps the table rows and import options it was built from, so each edit
changes those inputs and rebuilds the case with the same importer; the spec is never edited
by hand and never returned. A new case is planned from a draft by `case_edit_plan` with a
`draft_id` and saved by the existing `case_publish` approval.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .. import case_draft_store, workspace
from ..case_draft_store import Draft, DraftError
from ..pipe_table import PipeTable, PipeTableError, read_table
from ..pipe_table_endpoints import rows_from_endpoints
from ..pipe_table_import import (
    MAX_FLOWPATHS,
    MAX_NODES,
    MAX_SECTIONS,
    MAX_VALVES,
    ImportIssue,
    ImportOptions,
    ImportResult,
    build_case_spec,
)
from . import tool_locale
from .tool_validation import MAX_RESULT_BYTES, PathBindings, ToolError

PAGE_ROWS = 50
MAX_ISSUES = 20
MAX_BOUNDARIES = 20
_MAX_SPLIT_ROWS = 50
_MAX_MISSING_NODE_ROWS = 100
_MAX_MISSING_VALUE_ROWS = 20
# Codes a read refusal can carry in a result issue. Read refusals raise, so
# they never become ImportIssues and stay out of the import registries; the
# frontend fixture mirrors this tuple exactly (see test below).
READ_REFUSAL_CODES: tuple[str, ...] = (
    "table_encrypted",
)
_ISSUE_TEXT = 200
_NAME_TEXT = 48
_TABLE_SUFFIXES = {".csv", ".xlsx"}


def _issues(result: ImportResult) -> list[dict[str, Any]]:
    return [
        {
            "row": item.row,
            "field": str(item.field)[:64],
            "code": item.code,
            "params": dict(item.params),
            "reason": str(item.reason)[:_ISSUE_TEXT],
        }
        for item in result.issues[:MAX_ISSUES]
    ]


def _counts(summary: dict[str, Any]) -> dict[str, int]:
    keys = ("flowpaths", "pipes", "junctions", "boundaries", "valves", "sections")
    return {key: int(summary.get(key, 0)) for key in keys}


def _caps(counts: dict[str, int]) -> dict[str, dict[str, int]]:
    limits = {
        "nodes": (counts["junctions"] + counts["boundaries"], MAX_NODES),
        "flowpaths": (counts["flowpaths"], MAX_FLOWPATHS),
        "valves": (counts["valves"], MAX_VALVES),
        "sections": (counts["sections"], MAX_SECTIONS),
    }
    return {name: {"value": value, "limit": limit} for name, (value, limit) in limits.items()}


def _section_stats(summary: dict[str, Any]) -> dict[str, Any]:
    keys = ("shortest_section_m", "longest_section_m", "worst_ratio_in_flowpaths")
    return {key: summary.get(key) for key in keys}


def _boundaries(spec: Mapping[str, Any], label_map: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact boundary values keyed by imported label, with the table's node names."""
    table_names = {
        label: str(name)[:_NAME_TEXT] for name, label in label_map.get("nodes", {}).items()
    }
    flows = [item for item in spec.get("flowpaths", []) if isinstance(item, dict)]
    mass = {
        str(source.get("flowpath", "")): source
        for source in spec.get("massflow_sources") or []
        if isinstance(source, dict) and source.get("mass_flow_kg_s") is not None
    }
    out = []
    for node in spec.get("nodes", []):
        if not isinstance(node, dict) or node.get("kind") not in ("source", "sink", "closed"):
            continue
        label = str(node.get("label", ""))
        entry: dict[str, Any] = {
            "name": label, "node": table_names.get(label, ""), "kind": node.get("kind"),
        }
        if node.get("kind") in ("source", "sink"):
            entry.update({
                "pressure_bar": round(float(node["pressure_pa"]) / 100000.0, 6),
                "temperature_c": float(node["temperature_c"]),
                "gas_fraction": float(node["gas_fraction"]),
                "water_fraction": float(node["total_water_fraction"]),
            })
        else:
            flow = next((item.get("label", "") for item in flows if item.get("from") == label), "")
            feed = mass.get(flow)
            if feed is not None:
                entry.update({
                    "temperature_c": float(feed["temperature_c"]),
                    "gas_fraction": float(feed["gas_fraction"]),
                    "water_fraction": float(feed["total_water_fraction"]),
                    "mass_flow_kg_s": float(feed["mass_flow_kg_s"]),
                })
        out.append(entry)
    out.sort(key=lambda item: ({"source": 0, "sink": 1, "closed": 2}[item["kind"]], item["name"]))
    firsts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in out:
        if entry["kind"] not in seen:
            seen.add(entry["kind"])
            firsts.append(entry)
    kept = {id(entry) for entry in firsts}
    return firsts + [entry for entry in out if id(entry) not in kept]


def _boundaries_note(total: int, listed: int) -> str:
    """Note for omitted boundaries; worst when none are listed."""
    missing = total - listed
    noun = "boundary is" if missing == 1 else "boundaries are"
    return (
        f"{missing} more {noun} in the table but not listed here; their values "
        "were read from node rows and are in the draft, so do not ask the user "
        "for them and do not invent values; the draft review shows the boundary labels."
    )


def _split_note(locale: str | None) -> str:
    """Why the mid-pipe join was skipped, in `locale` (en/ko) or both."""
    english = (
        "The split pass was skipped for size, so pipe ends that touch "
        "other pipes mid-segment were left as separate ends; review the "
        "listed ends before adding node rows.")
    korean = (
        "크기가 커서 분할 단계를 건너뛰었어요. 다른 배관의 중간에 닿는 배관 끝은 "
        "따로 남겨 두었으니, 노드 행을 추가하기 전에 목록의 끝을 확인해 주세요.")
    if locale == "en":
        return english
    if locale == "ko":
        return korean
    return f"{english} {korean}"


def _endpoint_extras(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Pass through the module-capped ends and merged rows with their totals."""
    merged = [
        {"flowpath": entry.get("flowpath"), "rows": list(entry.get("rows", [])),
         "total": entry.get("total", len(list(entry.get("rows", []))))}
        for entry in list(summary.get("merged_rows", []))
    ]
    ends = list(summary.get("ends", []))
    out: dict[str, object] = {
        "ends": ends,
        "ends_total": summary.get("ends_total", len(ends)),
        "merged_rows": merged,
        "merged_rows_total": summary.get("merged_rows_total", len(merged)),
    }
    splits = list(summary.get("split_rows", []))
    if splits:
        out["split_rows"] = splits[:_MAX_SPLIT_ROWS]
        out["split_rows_total"] = len(splits)
    if summary.get("split_skipped"):
        out["split_skipped"] = True
        out["split_note"] = _split_note(tool_locale.current())
    return out


def _result_size(payload: dict[str, Any]) -> int:
    """JSON size in ASCII-escaped bytes, exactly what the wire cap measures.

    This must stay identical to ``tool_validation.cap``'s
    ``len(json.dumps(payload, default=str))`` (also what ``runtime`` sends);
    ``ensure_ascii=False`` under-counts non-ASCII names about 6x and lets a
    response pass here that the wire cap later cuts, dropping ``draft_id``.
    """
    return len(json.dumps(payload, default=str))


def _missing_node_rows(probe: dict[str, Any]) -> list[Any]:
    """The capped node-row names in a refusal's ``missing`` block, if any."""
    missing = probe.get("missing")
    if isinstance(missing, dict):
        rows = missing.get("node_rows")
        if isinstance(rows, list):
            return rows
    return []


def _shrink_to_totals(probe: dict[str, Any]) -> None:
    """Trim merged rows, then ends, then boundaries, then missing node rows to fit."""
    while _result_size(probe) > MAX_RESULT_BYTES and (
        probe.get("ends") or any(entry["rows"] for entry in probe.get("merged_rows", []))
        or probe.get("boundaries") or _missing_node_rows(probe)
    ):
        if any(entry["rows"] for entry in probe.get("merged_rows", [])):
            for entry in probe.get("merged_rows", []):
                entry["rows"] = []
        elif len(probe.get("ends") or []) > 1:
            probe["ends"] = probe["ends"][: len(probe["ends"]) // 2]
        elif probe.get("ends"):
            probe["ends"] = []
        elif probe.get("boundaries"):
            probe["boundaries"] = []
        elif len(_missing_node_rows(probe)) > 1:
            rows = _missing_node_rows(probe)
            probe["missing"]["node_rows"] = rows[: len(rows) // 2]
        elif isinstance(probe.get("missing"), dict) and "node_rows" in probe["missing"]:
            probe["missing"]["node_rows"] = []
        else:
            probe["boundaries"] = []


def _overview(draft: Draft) -> dict[str, Any]:
    counts = _counts(draft.summary)
    return {
        "draft_id": draft.draft_id,
        "revision": draft.revision,
        "source_name": draft.source_name[:_NAME_TEXT],
        "counts": counts,
        "caps": _caps(counts),
        "section_stats": _section_stats(draft.summary),
        "junction_warning_count": len(draft.summary.get("junction_ratio_warnings", [])),
        "initial_state": draft.summary.get("initial_state"),
        "start_warning": draft.summary.get("start_warning"),
        "coordinate_origin_assumed": draft.summary.get("coordinate_origin_assumed", False),
    }


def _bounded(payload: dict[str, Any]) -> dict[str, Any]:
    if _result_size(payload) > MAX_RESULT_BYTES:
        raise ToolError("The draft summary exceeds the safe result limit.")
    return payload


def load_draft(draft_id: str, generation: int) -> Draft:
    """Return a live draft of this workspace state, or refuse with a plain sentence."""
    try:
        return case_draft_store.get_draft(draft_id, context_generation=generation)
    except DraftError as exc:
        raise ToolError(str(exc)) from exc


def _import_options(stored: dict[str, Any]) -> ImportOptions:
    return ImportOptions(
        pvt_reference=stored["pvt_reference"],
        fluid_label=stored["fluid_label"],
        thermal=stored["thermal"],
        end_time_s=stored["end_time_s"],
        max_section_m=stored["max_section_m"],
        max_ratio=stored.get("max_ratio", 2.0),
        max_dt_s=stored.get("max_dt_s"),
        initial_pressure_pa=stored.get("initial_pressure_pa"),
        initial_temperature_c=stored.get("initial_temperature_c"),
    )


def _table(options: dict[str, Any]) -> PipeTable:
    return PipeTable(
        rows=tuple(options["rows"]),
        issues=(),
        header_row=options["header_row"],
        ignored_columns=(),
        sheet=options.get("sheet"),
        lines=tuple(options["lines"]),
    )


def import_table(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    """Read a workspace table and keep the case built from it as a private draft."""
    _root, generation = workspace.context_identity()
    column_map = args.get("column_map")
    if column_map is not None and not all(
        isinstance(key, str) and isinstance(value, str) for key, value in column_map.items()
    ):
        raise ToolError("column_map must map header names to template column names.")
    source = paths.input_file(str(args["path"]), _TABLE_SUFFIXES)
    try:
        table = read_table(
            source, column_map=column_map, sheet=args.get("sheet"), unit_length=args.get("unit_length"),
        )
    except PipeTableError as exc:
        if exc.code:
            return _bounded({
                "created": False,
                "issue_count": 1,
                "issues": [{
                    "row": None,
                    "field": "path",
                    "code": exc.code,
                    "params": {},
                    "reason": str(exc),
                }],
                "note": "No draft was made. The table needs these fixes first.",
            })
        raise ToolError(f"The table could not be read: {exc}") from exc
    except (OSError, KeyError, ElementTree.ParseError) as exc:
        raise ToolError(f"The table could not be read: {exc}") from exc
    layout = args.get("layout")
    if layout == "endpoints":
        if any(row.get("flowpath") not in (None, "") for row in table.rows):
            raise ToolError(
                "This is an ordinary pipe table, not an endpoints table: it has a "
                "flowpath column. Call pipe_table_import again without layout.")
        vertical_axis = args.get("vertical_axis")
        if vertical_axis not in ("y", "z"):
            raise ToolError("An endpoints table needs vertical_axis: the vertical coordinate ('y' or 'z').")
        roughness_m = args.get("roughness_m")
        if roughness_m is not None:
            try:
                roughness_m = float(roughness_m)
            except (TypeError, ValueError):
                raise ToolError("roughness_m must be a length in metres of zero or more.") from None
            if not math.isfinite(roughness_m) or roughness_m < 0:
                raise ToolError("roughness_m must be a length in metres of zero or more.")
    segmentation = args.get("segmentation") or {}
    stored = {
        "pvt_reference": args["pvt_reference"],
        "fluid_label": args["fluid_label"],
        "thermal": args["thermal"],
        "end_time_s": float(args["end_time_s"]),
        "max_section_m": float(segmentation.get("max_section_m", 1.0)),
        "max_ratio": float(segmentation.get("max_ratio", 2.0)),
    }
    if args.get("max_dt_s") is not None:
        stored["max_dt_s"] = float(args["max_dt_s"])
    initial = args.get("initial_conditions") or {}
    for key in ("pressure_pa", "temperature_c"):
        if key in initial:
            stored[f"initial_{key}"] = float(initial[key])
    endpoint_summary: dict[str, object] = {}
    if layout == "endpoints":
        reader_issues = tuple(
            ImportIssue(item.row, item.column, item.reason, item.code, dict(item.params))
            for item in table.issues
        )
        endpoint_rows, endpoint_issues, endpoint_summary = rows_from_endpoints(
            list(table.rows), vertical_axis=vertical_axis,
            roughness_m=roughness_m, lines=list(table.lines),
        )
        if endpoint_issues:
            early: dict[str, object] = {
                "created": False,
                "issue_count": len(reader_issues) + len(endpoint_issues),
                "issues": _issues(ImportResult(
                    spec=None, issues=reader_issues + tuple(endpoint_issues))),
                "note": "No draft was made. The table needs these fixes first.",
            }
            if layout == "endpoints":
                early.update(_endpoint_extras(endpoint_summary))
            return _bounded(early)
        table = PipeTable(
            rows=tuple(endpoint_rows), issues=tuple(table.issues),
            header_row=table.header_row, ignored_columns=table.ignored_columns,
            sheet=table.sheet, lines=tuple(endpoint_summary["row_lines"]),
        )
    result = build_case_spec(table, _import_options(stored))
    if result.spec is None:
        response: dict[str, object] = {
            "created": False,
            "issue_count": len(result.issues),
            "issues": _issues(result),
            "note": "No draft was made. The table needs these fixes first.",
        }
        if layout == "endpoints":
            response.update(_endpoint_extras(endpoint_summary))
            boundary_names = [
                str(issue.field)
                for issue in result.issues
                if issue.code == "missing_boundary_row"
            ]
            value_rows: dict[str, list[int]] = {}
            for issue in result.issues:
                if issue.code == "value_missing" and issue.row is not None:
                    field = str(issue.params.get("field", issue.field))
                    value_rows.setdefault(field, []).append(issue.row)
            response["missing"] = {
                "node_rows": boundary_names[:_MAX_MISSING_NODE_ROWS],
                "node_rows_total": len(boundary_names),
                "values": [
                    {"field": field, "rows": rows[:_MAX_MISSING_VALUE_ROWS]}
                    for field, rows in value_rows.items()
                ],
            }
            if boundary_names:
                response["next_step"] = (
                    "Add each missing END node row as a row in the table file "
                    "(columns node, node_kind, pressure_bar, temperature_c, "
                    "gas_fraction, water_fraction) instead of answering in "
                    "chat; ask in chat only for values the table does not hold.")
            _shrink_to_totals(response)
        return _bounded(response)
    options = {
        "kind": "pipe_table",
        "rows": [dict(row) for row in table.rows],
        "lines": list(table.lines),
        "header_row": table.header_row,
        "sheet": table.sheet,
        "import": stored,
    }
    unlimited = _boundaries(result.spec, result.label_map)
    total = len(unlimited)
    bounds = {
        "boundaries": unlimited[:MAX_BOUNDARIES],
        "boundaries_total": total,
    }
    preview: dict[str, object] = {}
    if layout == "endpoints":
        preview = _endpoint_extras(endpoint_summary)
    standin = Draft(
        draft_id="0" * 32, revision=1, context_generation=generation,
        created_at=0.0, expires_at=0.0, source_name=Path(source).name,
        spec=result.spec, summary=result.summary, label_map=result.label_map,
        options=options,
    )
    probe: dict[str, object] = {
        "created": True, **_overview(standin), "issue_count": 0, "issues": [],
        **preview, **bounds,
        "boundaries_note": _boundaries_note(total, 0),
    }
    _shrink_to_totals(probe)
    if layout == "endpoints":
        preview = {k: probe[k] for k in ("ends", "ends_total", "merged_rows", "merged_rows_total")}
        if "split_rows" in probe:
            preview["split_rows"] = probe["split_rows"]
            preview["split_rows_total"] = probe["split_rows_total"]
        if probe.get("split_skipped"):
            preview["split_skipped"] = True
            preview["split_note"] = probe["split_note"]
    bounds = {"boundaries": probe["boundaries"], "boundaries_total": total}
    try:
        draft = case_draft_store.create_draft(
            context_generation=generation,
            source_name=Path(source).name,
            spec=result.spec,
            summary=result.summary,
            label_map=result.label_map,
            options=options,
        )
    except DraftError as exc:
        raise ToolError(str(exc)) from exc
    created: dict[str, object] = {"created": True, **_overview(draft), "issue_count": 0, "issues": []}
    if layout == "endpoints":
        created.update(preview)
    created.update(bounds)
    if total > len(bounds["boundaries"]):
        created["boundaries_note"] = _boundaries_note(total, len(bounds["boundaries"]))
    return _bounded(created)


def _source_names(label_map: dict[str, Any], kind: str) -> dict[str, str]:
    return {label: str(name)[:_NAME_TEXT] for name, label in label_map.get(kind, {}).items()}


def review(args: dict[str, Any]) -> dict[str, Any]:
    """One page of the draft's flowpaths, 50 rows at a time, without the case itself."""
    _root, generation = workspace.context_identity()
    draft = load_draft(str(args["draft_id"]), generation)
    flowpaths = draft.spec["flowpaths"]
    pages = max(1, -(-len(flowpaths) // PAGE_ROWS))
    page = int(args.get("page", 1))
    if page > pages:
        raise ToolError(f"The draft has {pages} page(s); page {page} does not exist.")
    names = _source_names(draft.label_map, "flowpaths")
    start = (page - 1) * PAGE_ROWS
    rows = [
        {
            "label": item["label"],
            "source_name": names.get(item["label"], ""),
            "pipes": len(item["pipes"]),
            "sections": sum(pipe["sections"] for pipe in item["pipes"]),
            "from": item["from"],
            "to": item["to"],
        }
        for item in flowpaths[start:start + PAGE_ROWS]
    ]
    return _bounded({**_overview(draft), "page": page, "pages": pages, "flowpaths": rows})


def _resolve(label_map: dict[str, Any], kind: str, value: str) -> str:
    """The table's own name for a table name or a generated label."""
    names = label_map.get(kind, {})
    if value in names:
        return value
    for name, label in names.items():
        if label == value:
            return name
    raise ToolError(f"Unknown {kind[:-1]} {value[:_NAME_TEXT]!r}; use a name from the table or its label.")


def _schedule_text(schedule: list[dict[str, Any]]) -> str:
    return ", ".join(f"{float(point['time_s'])!r}:{float(point['opening'])!r}" for point in schedule)


def _apply(options: dict[str, Any], label_map: dict[str, Any], op: dict[str, Any]) -> str:
    kind = op["op"]
    stored = options["import"]
    if kind == "resegment":
        # Drafts written before max_ratio existed have no key; read it with the default.
        stored["max_ratio"] = stored.get("max_ratio", 2.0)
        if "max_section_m" in op:
            stored["max_section_m"] = op["max_section_m"]
        if "max_ratio" in op:
            stored["max_ratio"] = op["max_ratio"]
        if "max_section_m" not in op and "max_ratio" not in op:
            raise ToolError("resegment needs max_section_m or max_ratio.")
        return f"max section length {stored['max_section_m']:g} m, ratio {stored['max_ratio']:g}"
    if kind == "set_end_time":
        stored["end_time_s"] = _need(op, "end_time_s", kind)
        return f"end time {stored['end_time_s']:g} s"
    if kind == "set_valve_schedule":
        name = _resolve(label_map, "valves", str(_need(op, "valve", kind)))
        text = _schedule_text(_need(op, "schedule", kind))
        rows = [row for row in options["rows"] if str(row.get("valve") or "").strip() == name]
        for row in rows:
            row["valve_schedule"] = text
        return f"valve '{name[:_NAME_TEXT]}' schedule of {len(op['schedule'])} point(s)"
    if kind == "set_fluid":
        values = {key: op[key] for key in ("pvt_reference", "fluid_label") if key in op}
        if not values:
            raise ToolError("set_fluid needs pvt_reference or fluid_label.")
        stored.update(values)
        return "fluid " + ", ".join(sorted(values))
    if kind == "set_thermal":
        thermal = _need(op, "thermal", kind)
        if not isinstance(thermal, dict):
            raise ToolError("set_thermal needs a thermal object.")
        stored["thermal"] = thermal
        return f"thermal {str(thermal.get('model', ''))[:32]}"
    if kind == "set_boundary":
        name = _resolve(label_map, "nodes", str(_need(op, "node", kind)))
        values = {key: op[key] for key in ("pressure_pa", "temperature_c") if key in op}
        if not values:
            raise ToolError("set_boundary needs pressure_pa or temperature_c.")
        rows = [
            row for row in options["rows"]
            if not str(row.get("flowpath") or "").strip() and str(row.get("node") or "").strip() == name
        ]
        if not rows:
            raise ToolError(f"Node {name[:_NAME_TEXT]!r} has no boundary values to change.")
        for row in rows:
            row.update({key: float(value) for key, value in values.items()})
        return f"boundary '{name[:_NAME_TEXT]}' " + ", ".join(sorted(values))
    raise ToolError(f"Unknown draft edit {str(kind)[:32]!r}.")


def _need(op: dict[str, Any], key: str, kind: str) -> Any:
    if key not in op:
        raise ToolError(f"{kind} needs {key}.")
    return op[key]


def edit(args: dict[str, Any]) -> dict[str, Any]:
    """Apply typed edits to the draft's inputs, rebuild and re-validate, store a new revision."""
    _root, generation = workspace.context_identity()
    draft = load_draft(str(args["draft_id"]), generation)
    revision = int(args["revision"])
    if draft.revision != revision:
        raise ToolError("The draft changed since it was read; review it again first.")
    options = copy.deepcopy(draft.options)
    changes = [_apply(options, draft.label_map, dict(op)) for op in args["ops"]]
    result = build_case_spec(_table(options), _import_options(options["import"]))
    if result.spec is None:
        problems = "; ".join(
            f"{item.field}: {item.reason}"[:_ISSUE_TEXT] for item in result.issues[:3]
        )
        raise ToolError(f"The edit was not applied, the draft is unchanged. {problems}")
    try:
        updated = case_draft_store.update_draft(
            draft.draft_id, revision=revision, context_generation=generation,
            spec=result.spec, summary=result.summary, options=options,
        )
    except DraftError as exc:
        raise ToolError(str(exc)) from exc
    return _bounded({**_overview(updated), "applied": [change[:120] for change in changes]})
