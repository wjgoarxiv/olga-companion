"""Solver diagnostics + live-run monitoring adapters (T2).

Surfaces two previously-unwired toolkit scripts through the allowlisted run_tool
path plus a bounded local tail:

- `diagnose_out`  → solver_diagnostics.py --json (convergence, mass error, issue
  detection, fix suggestions). The script signals "issues found" via exit 1, so
  the JSON — not the exit code — decides usability (same contract as the report
  and evaluation adapters).
- `monitor_snapshot` → one-shot, byte-bounded reads of possibly growing solver
  evidence. It extracts timestep evidence, trend-file (`.tpl`) time evidence,
  and only an explicit vendor-authored completion percentage. File activity
  never decides process liveness or run state. It deliberately does NOT invoke
  run_monitor.py's blocking tail loop.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .genkey_static import OlgaInputError, run_tool

DIAGNOSTICS_SCRIPTS = {"solver_diagnostics": "solver_diagnostics.py"}

# Same timestep grammar solver_diagnostics/run_monitor rely on.
_RE_TIMESTEP = re.compile(
    r"--\*\+\+\*--\s+Time:\s+(\S+)s\.\s+Step no:\s+(\d+)/(\d+)\.\s+Current step-size:\s+(\S+)s"
)
_RE_VENDOR_PROGRESS = re.compile(
    r"Elapsed simulation-time is now:\s*(\S+)\s+(S|MIN|HOUR|H)\s*"
    r"\(\s*(\S+)% of simulation completed\s*\)",
    re.IGNORECASE,
)
_SNAPSHOT_TAIL_BYTES = 65536
_LIVENESS_STALE_SECONDS = 30.0
# Filesystem and host clocks can differ slightly across WSL/native boundaries.
# A timestamp farther into the future than this is evidence of clock skew, not
# fresh solver activity.
_CLOCK_SKEW_TOLERANCE_SECONDS = 2.0


def require_out_path(path_value: str) -> Path:
    """Resolve a .out/.log path for reading; reject dash-leading basenames."""
    if not path_value or not path_value.strip():
        raise OlgaInputError("A result log path is required.")
    path = Path(path_value).expanduser()
    if path.name.startswith("-"):
        raise OlgaInputError("Path basename must not start with '-'.")
    if path.suffix.lower() not in {".out", ".log"}:
        raise OlgaInputError("Expected an OLGA .out or .log solver log.")
    if not path.is_file():
        raise OlgaInputError(f"Log file not found: {path}")
    return path


def diagnose_out(path_value: str) -> dict[str, Any]:
    """Run solver_diagnostics --json. JSON decides usability, not the exit code."""
    path = require_out_path(path_value)
    result = run_tool(
        "solver_diagnostics", [str(path), "--json"], timeout_s=60, names=DIAGNOSTICS_SCRIPTS
    )
    payload: dict[str, Any] | None = None
    text = result.stdout.strip()
    brace = text.find("{")
    if brace != -1:
        try:
            payload = json.loads(text[brace:])
        except json.JSONDecodeError:
            payload = None
    usable = payload is not None and not result.timed_out
    issues = payload.get("issues", []) if payload else []
    return {
        "ok": usable,
        "path": str(path),
        "issues": issues,
        "issue_count": len(issues),
        "suggestions": payload.get("suggestions", []) if payload else [],
        "timesteps": payload.get("timesteps", []) if payload else [],
        "cpu_usage": payload.get("cpu_usage", []) if payload else [],
        "command": result.to_dict(),
    }


def _utc_timestamp(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_tail(path: Path, limit: int) -> dict[str, Any]:
    """Read one path through one handle, never requesting more than ``limit`` bytes."""
    try:
        with path.open("rb") as handle:
            file_stat = os.fstat(handle.fileno())
            offset = max(0, file_stat.st_size - limit)
            if offset:
                handle.seek(offset, os.SEEK_SET)
            payload = handle.read(limit)
    except FileNotFoundError:
        return {"status": "missing", "text": "", "mtime": None}
    except (PermissionError, OSError):
        return {"status": "unreadable", "text": "", "mtime": None}

    if not payload:
        return {"status": "empty", "text": "", "mtime": file_stat.st_mtime}
    text = payload.decode("utf-8", errors="replace")
    # A seek into a growing file usually lands in the middle of a line. Never
    # let that boundary fragment masquerade as a complete vendor record.
    if offset:
        newline = text.find("\n")
        text = "" if newline < 0 else text[newline + 1 :]
    return {"status": "read", "text": text, "mtime": file_stat.st_mtime}


def _finite_nonnegative(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _parse_timestep(text: str) -> tuple[dict[str, Any] | None, str]:
    latest: dict[str, Any] | None = None
    saw_marker = "--*++*--" in text or "Step no:" in text
    for match in _RE_TIMESTEP.finditer(text):
        sim_time_raw, step_raw, total_raw, step_size_raw = match.groups()
        sim_time = _finite_nonnegative(sim_time_raw)
        step_size = _finite_nonnegative(step_size_raw)
        try:
            step = int(step_raw)
            total = int(total_raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if sim_time is None or step_size is None or step < 0 or total <= 0:
            continue
        if total >= 2**31 or total < step:
            # Implausible denominator: keep the record, blank only the total.
            total = None
        latest = {
            "simulation_time_s": sim_time,
            "step": step,
            "adaptive_total_steps": total,
            "step_size_s": step_size,
        }
    if latest is not None:
        return latest, "valid"
    return None, "malformed" if saw_marker else "missing"


def _parse_vendor_progress(text: str) -> tuple[dict[str, Any] | None, str]:
    latest: dict[str, Any] | None = None
    saw_marker = "simulation completed" in text.lower() or "Elapsed simulation-time" in text
    # OLGA 2022.1 prints "H" once a run passes one hour.
    unit_seconds = {"S": 1.0, "MIN": 60.0, "HOUR": 3600.0, "H": 3600.0}
    for match in _RE_VENDOR_PROGRESS.finditer(text):
        simulation_raw, unit_raw, percent_raw = match.groups()
        simulation_value = _finite_nonnegative(simulation_raw)
        percent = _finite_nonnegative(percent_raw)
        if simulation_value is None or percent is None or percent > 100:
            continue
        latest = {
            "simulation_time_s": simulation_value * unit_seconds[unit_raw.upper()],
            "vendor_percent": percent,
            "fraction": percent / 100.0,
        }
    if latest is not None:
        return latest, "valid"
    return None, "malformed" if saw_marker else "missing"


def _sibling_trend_paths(out_path: Path) -> tuple[Path | None, Path | None]:
    """Same-stem ``.tpl``/``.ppl`` beside the ``.out`` in the same run folder.

    OLGA appends trend (``.tpl``) and profile (``.ppl``) results far more often
    than it rewrites the ``.out``, so their mtimes are file-activity evidence
    too. Returns ``None`` per side when no stem is derivable.
    """
    try:
        parent = out_path.parent
        stem = out_path.stem
    except (ValueError, RuntimeError):
        return None, None
    if not stem or stem in {".", ".."} or len(stem) > 255:
        return None, None
    return parent / f"{stem}.tpl", parent / f"{stem}.ppl"


def _parse_tpl_time(text: str) -> float | None:
    """Last time-row value of a bounded ``.tpl`` trend tail.

    Only rows after the last ``TIME SERIES`` marker count, so CATALOG counts
    and quoted header lines can never masquerade as simulation time. When the
    bounded window starts mid-data (marker scrolled out), every row is data;
    trend rows always carry time plus values, so single-column lines are never
    time evidence.
    """
    body = text.rsplit("TIME SERIES", 1)[-1] if "TIME SERIES" in text else text
    latest: float | None = None
    for line in body.splitlines():
        tokens = line.split()
        if len(tokens) < 2:
            continue
        value = _finite_nonnegative(tokens[0])
        if value is not None:
            latest = value
    return latest


def monitor_snapshot(path_value: str, run_log_value: str | None = None) -> dict[str, Any]:
    """Return bounded, non-authoritative solver evidence without raising on I/O races.

    The ``Step no: current/total`` denominator is adaptive and is deliberately
    retained only as raw evidence. A fraction exists only when ``run.log`` has a
    finite, explicit vendor-authored percentage in the closed interval 0..100.
    File activity (``activity_status``/``age_seconds``/``file_timestamp``)
    reflects the newest of the ``.out``, ``run.log``, and the same-stem
    ``.tpl``/``.ppl`` in the same folder. When the ``.out`` has no timestep
    line yet, ``simulation_time_s`` falls back to the last ``.tpl`` time row.
    """
    out_path = Path(path_value).expanduser()
    log_path = Path(run_log_value).expanduser() if run_log_value else None
    out_tail = _bounded_tail(out_path, _SNAPSHOT_TAIL_BYTES)
    log_tail = (
        _bounded_tail(log_path, _SNAPSHOT_TAIL_BYTES)
        if log_path is not None
        else {"status": "missing", "text": "", "mtime": None}
    )
    tpl_path, ppl_path = _sibling_trend_paths(out_path)
    tpl_tail = (
        _bounded_tail(tpl_path, _SNAPSHOT_TAIL_BYTES)
        if tpl_path is not None
        else {"status": "missing", "text": "", "mtime": None}
    )
    # The `.ppl` contributes file-activity evidence only; its content is never
    # parsed. The read stays byte-bounded like every other tail here.
    ppl_tail = (
        _bounded_tail(ppl_path, _SNAPSHOT_TAIL_BYTES)
        if ppl_path is not None
        else {"status": "missing", "text": "", "mtime": None}
    )

    timestep, timestep_status = _parse_timestep(str(out_tail["text"]))
    vendor, vendor_status = _parse_vendor_progress(str(log_tail["text"]))
    if out_tail["status"] != "read":
        timestep_status = str(out_tail["status"])
    if log_tail["status"] != "read":
        vendor_status = str(log_tail["status"])
    tpl_time = _parse_tpl_time(str(tpl_tail["text"]))
    if tpl_tail["status"] != "read":
        trend_status = str(tpl_tail["status"])
    elif tpl_time is not None:
        trend_status = "valid"
    else:
        trend_status = "missing"

    valid = timestep is not None or tpl_time is not None or vendor is not None
    source_statuses = {str(out_tail["status"]), str(log_tail["status"])}
    evidence_statuses = {timestep_status, vendor_status}
    if valid:
        parse_status = "parsed"
    elif "unreadable" in source_statuses:
        parse_status = "unreadable"
    elif "malformed" in evidence_statuses:
        parse_status = "malformed"
    elif source_statuses <= {"missing"}:
        parse_status = "missing"
    elif source_statuses <= {"missing", "empty"}:
        parse_status = "empty"
    else:
        parse_status = "indeterminate"

    mtimes = [
        float(value)
        for value in (
            out_tail.get("mtime"),
            log_tail.get("mtime"),
            tpl_tail.get("mtime"),
            ppl_tail.get("mtime"),
        )
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    ]
    latest_mtime = max(mtimes) if mtimes else None
    age_seconds = round(time.time() - latest_mtime, 3) if latest_mtime is not None else None
    activity_status = (
        "unavailable"
        if age_seconds is None
        else "clock_skew"
        if age_seconds < -_CLOCK_SKEW_TOLERANCE_SECONDS
        else "active"
        if age_seconds <= _LIVENESS_STALE_SECONDS
        else "stale"
    )
    simulation_time_s = (
        timestep["simulation_time_s"]
        if timestep is not None
        else tpl_time
        if tpl_time is not None
        else vendor["simulation_time_s"]
        if vendor is not None
        else None
    )
    return {
        "parse_status": parse_status,
        "activity_status": activity_status,
        "observed_at": _utc_timestamp(time.time()),
        "file_timestamp": _utc_timestamp(latest_mtime) if latest_mtime is not None else None,
        "age_seconds": age_seconds,
        "simulation_time_s": simulation_time_s,
        "step": timestep["step"] if timestep is not None else None,
        "adaptive_total_steps": timestep["adaptive_total_steps"] if timestep is not None else None,
        "step_size_s": timestep["step_size_s"] if timestep is not None else None,
        "vendor_percent": vendor["vendor_percent"] if vendor is not None else None,
        "fraction": vendor["fraction"] if vendor is not None else None,
        "phase": "indeterminate",
        "liveness": "indeterminate",
        "files": {
            "out": out_path.name,
            "run_log": log_path.name if log_path is not None else None,
        },
        "evidence": {
            "timestep": timestep_status,
            "vendor_percent": vendor_status,
            "trend": trend_status,
        },
    }


def diagnostics_capabilities() -> dict[str, Any]:
    from .genkey_static import toolkit_dir

    script = toolkit_dir() / "scripts" / DIAGNOSTICS_SCRIPTS["solver_diagnostics"]
    if script.exists():
        return {"enabled": True, "reason": "Solver diagnostics toolkit script detected."}
    return {"enabled": False, "reason": f"Missing toolkit script: {script.name}."}
