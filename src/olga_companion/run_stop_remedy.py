"""Where a stopped run's own words point in the edit table.

Only a place is returned, never a value: the user types the value, and the edit goes through the
table's usual review and approval. A stop OLGA reports as a fluid-table range, or one this reader
does not recognise, points nowhere and says why.
"""

from __future__ import annotations

from typing import Any

from .case_lint import table_path


def _none(reason: str) -> dict[str, Any]:
    return {"row_id": None, "reason_key": reason}


def remedy_for(stop_reason: dict[str, Any] | None, rows: list[dict[str, Any]], coverage: dict[str, list[str]]) -> dict[str, Any]:
    """The edit-table row the stop names, or None with the reason it cannot be pointed at."""
    code = (stop_reason or {}).get("code")
    if isinstance(code, str) and code.endswith("_table"):
        return _none("table_range")
    pointer = (stop_reason or {}).get("pointer") or {}
    if code != "input_rejected" or pointer.get("kind") != "keyword":
        return _none("unknown")
    path = f"{str(pointer.get('keyword', '')).upper()}.{str(pointer.get('key', '')).upper()}"
    if path not in coverage.get("table", []):
        if path in coverage.get("sweep", []):
            return _none("sweep_only")
        if path in coverage.get("fixed", []):
            return _none("fixed")
        return _none("not_editable")
    matches = [row for row in rows if table_path(row) == path]
    if len(matches) > 1:
        component = str(pointer.get("component", "")).lower()
        matches = [row for row in matches if component and component in str(row.get("target", "")).lower().split("/")]
    if len(matches) != 1:
        return _none("ambiguous")
    return {"row_id": matches[0]["id"], "reason_key": "row"}
