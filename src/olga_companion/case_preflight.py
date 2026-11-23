"""A read-only checklist of one workspace .genkey before a run.

Every item comes from a check the app already makes: the static validator, the edit table's
values, the case lint rules, and the fluid-table range flags. Nothing here writes a file or
starts OLGA, and nothing adds a threshold of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import case_edit_table, case_lint, genkey_static, pvt_range

_RULE_ROWS = {
    "endtime_missing": "integration.end_time_s",
    "mindt_above_maxdt": "integration.min_dt_s",
    "dtstart_above_maxdt": "integration.dt_start_s",
}
_DTPLOT_ROWS = {"TREND": "integration.trend_interval_s", "PROFILE": "integration.profile_interval_s"}
_PIPE_FIELDS = {"diameter_not_positive": "diameter_m", "roughness_vs_diameter": "roughness_m"}
_PVT_FIELDS = {"pressure": "pressure_pa", "temperature": "temperature_c"}


def _item(item_id: str, state: str, code: str, row_id: str | None = None, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"id": item_id, "state": state, "message_code": code}
    if row_id is not None:
        item["row_id"] = row_id
    item.update({key: value for key, value in extra.items() if value is not None})
    return item


def _validation(source: Path) -> dict[str, Any]:
    result = genkey_static.run_tool("validator", [str(source)])
    if result.exit_code == 0 and not result.timed_out:
        return _item("validation", "ok", "validation_clean")
    # Only an error line the validator printed is an input error; a timeout, the output limit or a
    # crash means the check did not finish, and the file may be fine.
    errors = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("[X")]
    if result.timed_out or not errors:
        return _item("validation", "warn", "validation_unavailable")
    return _item("validation", "warn", "validation_failed", detail=errors[0][:280])


def _rule_row(warning: dict[str, Any], row_ids: set[str]) -> str | None:
    rule = warning["rule"]
    if rule == "dtplot_above_endtime":
        candidate = _DTPLOT_ROWS.get(warning["keyword"])
    elif rule in _PIPE_FIELDS:
        suffix = f".pipes.{warning['values'].get('label')}.{_PIPE_FIELDS[rule]}"
        candidate = next((row_id for row_id in sorted(row_ids) if row_id.endswith(suffix)), None)
    else:
        candidate = _RULE_ROWS.get(rule)
    return candidate if candidate in row_ids else None


def _rule_items(source: Path, row_ids: set[str]) -> list[dict[str, Any]]:
    items = []
    for warning in case_lint.lint_case(source):
        rule = warning["rule"]
        label = warning["values"].get("label")
        suffix = label if label else (warning["keyword"] if rule == "dtplot_above_endtime" else None)
        item_id = f"rule:{rule}" + (f":{suffix}" if suffix else "")
        state = "missing" if rule == "endtime_missing" else "warn"
        values = {"keyword": warning["keyword"], **warning["values"]}
        items.append(_item(item_id, state, rule, _rule_row(warning, row_ids), target=label, values=values))
    return items


def _pvt_items(source: Path, row_ids: set[str]) -> list[dict[str, Any]]:
    items = []
    for flag in pvt_range.range_flags(source):
        origin, quantity = flag["origin"], flag["quantity"]
        row_id = f"nodes.{origin}.{_PVT_FIELDS.get(quantity, quantity)}"
        code = "pvt_outside" if flag["status"] == "outside" else "pvt_near_edge"
        items.append(_item(f"pvt:{origin}:{quantity}", "warn", code, row_id if row_id in row_ids else None,
                           target=origin, values=dict(flag)))
    return items


def preflight(source: Path) -> dict[str, Any]:
    """The checklist for one case; `source` is already resolved inside the workspace."""
    rows = case_edit_table.editable_rows(source)["rows"]
    row_ids = {row["id"] for row in rows}
    items = [_validation(source)]
    items.extend(
        _item(f"row:{row['id']}", "missing", "value_unset", row["id"], target=row["target"], field=row["field"])
        for row in rows if row["value"] is None
    )
    items.extend(_rule_items(source, row_ids))
    items.extend(_pvt_items(source, row_ids))
    return {"items": items}
