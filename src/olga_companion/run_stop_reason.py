"""Why a run stopped, read only from OLGA's own stop message.

Every field comes from the run's .out file or log: the abort time, the table-range message with its
pressure and temperature, where OLGA reported it, and the exit message. A stop this reader does not
recognise is `unknown`, with OLGA's last lines (paths removed) so the user still sees the real words.
"""

from __future__ import annotations

import re
from typing import Any

from .patrol_sanitization import safe_diagnostic_text

_ABORTED = re.compile(r"ABORTED AT TIME\s+([-+0-9.Ee]+)\s+SECONDS", re.IGNORECASE)
_TABLE = re.compile(
    r"(PRESSURE|TEMPERATURE)\s+(ABOVE|BELOW)\s+TABLE VALUES\s*\(\s*P\s*=\s*([-+0-9.Ee]+)\s*bara\s*,\s*T\s*=\s*([-+0-9.Ee]+)\s*C\s*\)",
    re.IGNORECASE,
)
_WHERE = re.compile(r"REPORTED IN\s+(.+?)\.?\s*$", re.IGNORECASE | re.MULTILINE)
_EXIT = re.compile(r"exit message\s+'([^']{1,80})'\s*\((\d+)\)", re.IGNORECASE)
_LAST_LINES = 12
_LINE_LIMIT = 200


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def _last_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not set(line.strip()) <= {"*"}]
    return [safe_diagnostic_text(line, _LINE_LIMIT) for line in lines[-_LAST_LINES:]]


def explain_stop(out_text: str, log_text: str, exit_code: int | None) -> dict[str, Any]:
    """The cause OLGA gave for stopping, or `unknown` with its last lines."""
    text = f"{out_text}\n{log_text}"
    aborted = _ABORTED.search(text)
    table = _TABLE.search(text)
    where = _WHERE.search(text)
    exit_match = _EXIT.search(text)
    code = "unknown"
    if table:
        code = f"{table.group(1).lower()}_{table.group(2).lower()}_table"
    return {
        "code": code,
        "stopped_at_s": _number(aborted.group(1)) if aborted else None,
        "pressure_bara": _number(table.group(3)) if table else None,
        "temperature_c": _number(table.group(4)) if table else None,
        "where": safe_diagnostic_text(where.group(1).strip(), 120) if where else None,
        "exit_code": int(exit_match.group(2)) if exit_match else exit_code,
        "exit_message": exit_match.group(1).strip() if exit_match else None,
        "last_lines": _last_lines(log_text or out_text),
    }
