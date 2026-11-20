"""Bounded solver findings for a failed or cancelled run status."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .diagnostics import diagnose_out
from .patrol_sanitization import safe_diagnostic_text
from .run_stop_reason import explain_stop

EXPLAINED_STATES = frozenset({"failed", "cancelled"})
_MAX_FINDINGS = 8
_TEXT_LIMIT = 240
_OUT_TAIL_BYTES = 16_384
_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
_MESSAGES = {
    "DTMIN_HIT": "최소 시간 간격에 닿았습니다.",
    "NEGATIVE_HOLDUP": "체적 분율이 음수입니다.",
    "NAN_VALUE": "계산 값에 숫자가 아닌 값이 있습니다.",
    "STALLED": "시뮬레이션 시간이 늘지 않았습니다.",
    "MASS_ERROR": "질량 오차가 큽니다.",
}


def findings_for_out(path_value: str) -> list[dict[str, Any]]:
    """Reuse diagnose_out and return a short, path-safe finding list."""
    path = Path(path_value)
    try:
        stat = path.stat()
    except OSError:
        return []
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        raw = diagnose_out(str(path))
    except Exception:  # noqa: BLE001 — a missing toolkit must not hide the run status
        projected: list[dict[str, Any]] = []
    else:
        projected = _project(raw)
    _CACHE[key] = projected
    if len(_CACHE) > 32:
        _CACHE.pop(next(iter(_CACHE)))
    return projected


def attach_solver_findings(status: dict[str, Any]) -> None:
    """Add findings only for a failed or cancelled run that has an .out file."""
    if status.get("state") not in EXPLAINED_STATES:
        status["solver_findings"] = []
        status["stop_reason"] = None
        return
    findings = _findings_from_outputs(status.get("outputs"))
    exit_code = status.get("exit_code")
    status["stop_reason"] = explain_stop(
        _out_tail(status.get("outputs")),
        str(status.get("log_tail") or ""),
        exit_code if isinstance(exit_code, int) else None,
    )
    status["solver_findings"] = findings
    failure = status.get("failure")
    if isinstance(failure, dict):
        failure["solver_findings"] = findings


def _findings_from_outputs(outputs: Any) -> list[dict[str, Any]]:
    if not isinstance(outputs, list):
        return []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        suffix = str(output.get("suffix") or "").lower()
        name = str(output.get("name") or "")
        path = output.get("path")
        if suffix != ".out" and not name.lower().endswith(".out"):
            continue
        if isinstance(path, str) and path:
            return findings_for_out(path)
    return []


def _project(raw: dict[str, Any]) -> list[dict[str, Any]]:
    issues = raw.get("issues") if isinstance(raw.get("issues"), list) else []
    suggestions = _suggestions_by_code(raw.get("suggestions"))
    findings: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict) or len(findings) >= _MAX_FINDINGS:
            break
        code = safe_diagnostic_text(issue.get("type") or issue.get("code"), 40)
        if not code:
            continue
        time = issue.get("time")
        line = issue.get("line_no")
        findings.append(
            {
                "code": code,
                "message": _MESSAGES.get(code, "솔버가 이상을 보고했습니다."),
                "evidence": safe_diagnostic_text(issue.get("message"), _TEXT_LIMIT),
                "line": line if isinstance(line, int) and line > 0 else None,
                "time": time if isinstance(time, (int, float)) and math.isfinite(time) else None,
                "suggestion": suggestions.get(code),
            }
        )
    return findings


def _suggestions_by_code(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    mapped: dict[str, str] = {}
    for item in value:
        text = safe_diagnostic_text(item, _TEXT_LIMIT)
        code, _, rest = text.partition(":")
        code = code.strip()
        if code and code not in mapped:
            mapped[code] = rest.strip() or text
    return mapped


def _out_tail(outputs: Any) -> str:
    """The end of the run's .out file, where OLGA writes its stop message; empty when there is none."""
    if not isinstance(outputs, list):
        return ""
    for output in outputs:
        if not isinstance(output, dict):
            continue
        name = str(output.get("name") or "").lower()
        path = output.get("path")
        if (str(output.get("suffix") or "").lower() == ".out" or name.endswith(".out")) and isinstance(path, str) and path:
            try:
                with open(path, "rb") as handle:
                    handle.seek(0, 2)
                    handle.seek(max(0, handle.tell() - _OUT_TAIL_BYTES))
                    return handle.read().decode("utf-8", errors="replace")
            except OSError:
                return ""
    return ""
