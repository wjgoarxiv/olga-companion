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
_NODE = re.compile(r"NODE\s+([A-Za-z0-9_\-]+)", re.IGNORECASE)
_PIPE = re.compile(
    r"FLOWPATH\s*=\s*([A-Za-z0-9_\-]+)\s*,\s*PIPE\s*=\s*([A-Za-z0-9_\-]+)\s*,\s*SECTION\s*=\s*(\d+)",
    re.IGNORECASE,
)
# OLGA's input check: the component tag on its own line, then "KEYWORD: ... key KEY ...".
_REJECTED = re.compile(
    r"^[ \t]*([A-Za-z][A-Za-z0-9_\-]*)[ \t]*\r?\n[ \t]*([A-Z][A-Z0-9_]*):[^\n]*?\bkey\s+([A-Z][A-Z0-9_]*)\b[^\n]*",
    re.MULTILINE,
)
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


def _line(text: str, match: re.Match[str]) -> str:
    """The whole line a match sits on, paths removed."""
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    return safe_diagnostic_text(text[start : len(text) if end < 0 else end].strip(), _LINE_LIMIT)


def _pointer(where: str | None) -> dict[str, Any] | None:
    """The place OLGA named, only when its whole text is a node or a pipe section."""
    if not where:
        return None
    node = _NODE.fullmatch(where.strip())
    if node:
        return {"kind": "node", "label": node.group(1)}
    pipe = _PIPE.fullmatch(where.strip())
    if pipe:
        return {"kind": "pipe", "flowpath": pipe.group(1), "label": pipe.group(2), "section": int(pipe.group(3))}
    return None


def explain_stop(out_text: str, log_text: str, exit_code: int | None) -> dict[str, Any]:
    """The cause OLGA gave for stopping, or `unknown` with its last lines."""
    text = f"{out_text}\n{log_text}"
    aborted = _ABORTED.search(text)
    table = _TABLE.search(text)
    where = _WHERE.search(text)
    exit_match = _EXIT.search(text)
    rejected = None if table else _REJECTED.search(text)
    code = "unknown"
    where_text = where.group(1).strip() if where else None
    pointer = None
    evidence_match = table or rejected or exit_match or aborted
    if table:
        code = f"{table.group(1).lower()}_{table.group(2).lower()}_table"
        pointer = _pointer(where_text)
    elif rejected:
        code = "input_rejected"
        pointer = {"kind": "keyword", "component": rejected.group(1), "keyword": rejected.group(2), "key": rejected.group(3)}
    evidence = None
    if evidence_match is rejected and rejected is not None:
        evidence = safe_diagnostic_text(text[text.index("\n", rejected.start(1)) + 1 : rejected.end()].strip(), _LINE_LIMIT)
    elif evidence_match is not None:
        evidence = _line(text, evidence_match)
    return {
        "code": code,
        "stopped_at_s": _number(aborted.group(1)) if aborted else None,
        "pressure_bara": _number(table.group(3)) if table else None,
        "temperature_c": _number(table.group(4)) if table else None,
        "where": safe_diagnostic_text(where_text, 120) if where_text else None,
        "evidence": evidence,
        "pointer": pointer,
        "exit_code": int(exit_match.group(2)) if exit_match else exit_code,
        "exit_message": exit_match.group(1).strip() if exit_match else None,
        "last_lines": _last_lines(log_text or out_text),
    }
