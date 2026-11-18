"""Warn-only checks on the exact .genkey about to run, and which keys the app can change.

Read-only: nothing here edits a case or blocks a run. Each warning is a rule id plus the
values it saw, so the screen words it in the UI language. A value the checks cannot read
for sure (an unknown unit, a list where a number is expected) gives no warning.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from .fluids import strip_genkey_comments
from .units import UnitConversionError, convert_values

_RECORD: Final = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\b(.*)$")
_ASSIGNMENT: Final = re.compile(
    r"(?:^|,)\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*"
    r"(?:\(([^)]*)\)\s*([^,\s]*)|\"([^\"]*)\"|'([^']*)'|([^,]*))"
)
_NUMBER: Final = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([^\s,]*)\s*$")

ROUGHNESS_LIMIT: Final = 0.05


def _records(text: str) -> list[tuple[str, dict[str, tuple[str, list[str] | None, str | None]]]]:
    """(KEYWORD, {KEY: (kind, list items or None, unit or scalar text)}) per logical record."""
    out = []
    pending = ""
    for raw in strip_genkey_comments(text).replace("\r", "").split("\n"):
        line = raw.strip()
        if not pending and not line:
            continue
        continues = line.endswith("\\")
        pending = f"{pending} {line[:-1].rstrip() if continues else line}".strip()
        if continues:
            continue
        match = _RECORD.match(pending)
        pending = ""
        if match is None:
            continue
        values: dict[str, tuple[str, list[str] | None, str | None]] = {}
        for item in _ASSIGNMENT.finditer(match.group(2)):
            key = item.group(1).upper()
            if item.group(2) is not None:
                values[key] = ("list", [part.strip() for part in item.group(2).split(",")], item.group(3) or None)
            elif item.group(6) is not None:
                values[key] = ("scalar", None, item.group(6).strip())
            else:
                values[key] = ("text", None, item.group(4) if item.group(4) is not None else item.group(5))
        out.append((match.group(1).upper(), values))
    return out


def _si(value: float, unit: str | None, target: str) -> float | None:
    if not unit:
        return None
    try:
        converted = convert_values([value], unit, target)
    except UnitConversionError:
        return None
    if converted["conversion"]["status"] == "source_only" and unit.casefold() != target.casefold():
        return None
    return float(converted["values"][0])


def _scalar(values: dict[str, Any], key: str, target: str) -> float | None:
    entry = values.get(key)
    if entry is None or entry[0] != "scalar" or entry[2] is None:
        return None
    match = _NUMBER.match(entry[2])
    if match is None:
        return None
    return _si(float(match.group(1)), match.group(2) or None, target)


def _numbers(values: dict[str, Any], key: str, target: str) -> list[float] | None:
    entry = values.get(key)
    if entry is None or entry[0] != "list":
        return None
    numbers = []
    for part in entry[1]:
        try:
            number = float(part)
        except ValueError:
            return None
        converted = _si(number, entry[2], target)
        if converted is None:
            return None
        numbers.append(converted)
    return numbers


def _label(values: dict[str, Any]) -> str:
    entry = values.get("LABEL")
    return entry[2] if entry and entry[2] else "?"


def _warn(rule: str, keyword: str, **values: Any) -> dict[str, Any]:
    return {"rule": rule, "keyword": keyword, "values": {k: v for k, v in values.items() if v is not None}}


def lint_text(text: str) -> list[dict[str, Any]]:
    records = _records(text)
    warnings: list[dict[str, Any]] = []
    integration = next((values for keyword, values in records if keyword == "INTEGRATION"), None)
    end = _scalar(integration, "ENDTIME", "s") if integration else None
    if integration is None or "ENDTIME" not in integration:
        warnings.append(_warn("endtime_missing", "INTEGRATION"))
    if integration is not None:
        min_dt = _scalar(integration, "MINDT", "s")
        max_dt = _scalar(integration, "MAXDT", "s")
        start_dt = _scalar(integration, "DTSTART", "s")
        if min_dt is not None and max_dt is not None and min_dt > max_dt:
            warnings.append(_warn("mindt_above_maxdt", "INTEGRATION", value=min_dt, limit=max_dt, unit="s"))
        if start_dt is not None and max_dt is not None and start_dt > max_dt:
            warnings.append(_warn("dtstart_above_maxdt", "INTEGRATION", value=start_dt, limit=max_dt, unit="s"))
    for keyword, values in records:
        if keyword in ("TREND", "PROFILE") and end is not None:
            step = _scalar(values, "DTPLOT", "s")
            if step is not None and step > end:
                warnings.append(_warn("dtplot_above_endtime", keyword, value=step, limit=end, unit="s"))
        if keyword != "PIPE":
            continue
        label = _label(values)
        diameter = _scalar(values, "DIAMETER", "m")
        if diameter is not None and diameter <= 0:
            warnings.append(_warn("diameter_not_positive", "PIPE", label=label, value=diameter, unit="m"))
        segments = _numbers(values, "LSEGMENT", "m")
        if segments is not None and any(length <= 0 for length in segments):
            warnings.append(_warn("segment_not_positive", "PIPE", label=label))
        count = values.get("NSEGMENT")
        if segments is not None and count and count[0] == "scalar" and count[2] and count[2].isdigit():
            if int(count[2]) != len(segments):
                warnings.append(_warn("nsegment_mismatch", "PIPE", label=label, value=int(count[2]), limit=len(segments)))
        roughness = _scalar(values, "ROUGHNESS", "m")
        if roughness is not None and diameter is not None and diameter > 0 and roughness / diameter > ROUGHNESS_LIMIT:
            warnings.append(_warn("roughness_vs_diameter", "PIPE", label=label, value=roughness, limit=diameter, unit="m"))
    return warnings


def lint_case(path: Path) -> list[dict[str, Any]]:
    return lint_text(path.read_text(encoding="utf-8", errors="replace"))


# Edit-table operation -> the GENKEY keyword.key it changes.
_TABLE_PATHS: Final = {
    "set_integration": "INTEGRATION.ENDTIME",
    "set_boundary_pressure": "PARAMETERS.PRESSURE",
    "set_boundary_temperature": "PARAMETERS.TEMPERATURE",
    "set_source_massflow": "SOURCE.MASSFLOW",
    "set_valve_opening": "VALVE.OPENING",
    "set_pipe_roughness": "PIPE.ROUGHNESS",
}


def keyword_coverage(path: Path, rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Every keyword.key in the case, in one of three groups: the edit table changes it (a
    reviewed new copy), a sweep can vary it (copies only), or the app cannot change it
    (the case sets it more than once, so a change could hit the wrong one)."""
    from .sweep_parameters import sweep_parameter_catalog

    unique, ambiguous = sweep_parameter_catalog(path)
    table = sorted({_TABLE_PATHS[row["op"]["op"]] for row in rows if row.get("op", {}).get("op") in _TABLE_PATHS})
    in_table = set(table)
    return {
        "table": table,
        "sweep": sorted({item.path for item in unique} - in_table),
        "fixed": sorted(set(ambiguous) - in_table),
    }
