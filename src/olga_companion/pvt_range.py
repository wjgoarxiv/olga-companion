"""PVT table range precheck for runs and CaseSpec validation.

A case whose boundary or source pressure or temperature leaves the linked
PVT table grid stops the OLGA solver with PRESSURE BELOW TABLE VALUES. This
module compares every such value with the table P/T range read through the
toolkit ``tab_parser`` before anything launches. An unreadable table, a
missing file, an unknown unit, or a case without a PVTFILE behaves as today:
the check is skipped, never guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from . import fluids, genkey_static, pipe_table_import, workspace

Status = Literal["inside", "near", "outside"]

NEAR_FRACTION = 0.10
ATMOSPHERE_PA = 101_325.0

_PRESSURE_TO_PA: dict[str, tuple[float, float]] = {
    "pa": (1.0, 0.0),
    "kpa": (1_000.0, 0.0),
    "mpa": (1_000_000.0, 0.0),
    "bar": (100_000.0, 0.0),
    "bara": (100_000.0, 0.0),
    "barg": (100_000.0, ATMOSPHERE_PA),
    "atm": (ATMOSPHERE_PA, 0.0),
    "atma": (ATMOSPHERE_PA, 0.0),
    "atmg": (ATMOSPHERE_PA, ATMOSPHERE_PA),
    "psi": (6_894.757293168, 0.0),
    "psia": (6_894.757293168, 0.0),
    "psig": (6_894.757293168, ATMOSPHERE_PA),
    "mmhg": (133.322387415, 0.0),
    "inwg": (249.08891, ATMOSPHERE_PA),
    "at": (98_066.5, 0.0),
    "atg": (98_066.5, ATMOSPHERE_PA),
}

_SAFE_UNIT = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _.-"
)

# A 0-50 C table aborted a 5->2 bar run on temperature: narrow grids never vouch for a large step.
NARROW_TEMPERATURE_SPAN_C = 50.0


@dataclass(frozen=True)
class TabRange:
    """A linked table grid in SI units; temperatures stay None for PH tables."""

    p_min_pa: float
    p_max_pa: float
    t_min_c: float | None
    t_max_c: float | None
    tab: str


@dataclass(frozen=True)
class RangeEntry:
    """One case value compared against the table grid, already in SI units."""

    origin: str
    kind: str  # "node" or "source"
    quantity: str  # "pressure" or "temperature"
    value_si: float
    display: str
    field: str


def _safe_unit(unit: object) -> str | None:
    if not isinstance(unit, str) or not unit or len(unit) > 16:
        return None
    if any(char not in _SAFE_UNIT or char in "/\\" for char in unit):
        return None
    return unit


def pressure_to_pa(value: object, unit: object) -> float | None:
    """Absolute pascal for an OLGA pressure value, or None when unknown."""
    clean = _safe_unit(unit)
    if clean is None or not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    scale = _PRESSURE_TO_PA.get(clean.casefold())
    if scale is None:
        return None
    result = float(value) * scale[0] + scale[1]
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def temperature_to_c(value: object, unit: object) -> float | None:
    """Degrees Celsius for an OLGA temperature value, or None when unknown."""
    clean = _safe_unit(unit)
    if clean is None or not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    key = clean.casefold()
    number = float(value)
    if key in {"c", "degc"}:
        result = number
    elif key == "k":
        result = number - 273.15
    elif key in {"f", "degf"}:
        result = (number - 32.0) * 5.0 / 9.0
    elif key in {"r", "degr"}:
        result = (number - 491.67) * 5.0 / 9.0
    else:
        return None
    return result if result == result and abs(result) != float("inf") else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _edge_eps(bound: float) -> float:
    """Absolute slack for one grid edge. Unit conversion can miss an exact edge by a few ulps."""
    return 1e-9 * max(1.0, abs(bound))


def _same_text(left: object, right: str) -> bool:
    return isinstance(left, str) and left.casefold() == right.casefold()


def _lookup(params: Mapping[str, Any], key: str) -> Any:
    for existing, value in params.items():
        if _same_text(existing, key):
            return value
    return None


def _scalar(params: Mapping[str, Any], key: str) -> tuple[Any, Any]:
    """Split a parsed keyword value into its magnitude and unit text."""
    raw = _lookup(params, key)
    if isinstance(raw, Mapping):
        return raw.get("value"), raw.get("unit")
    return raw, None


def _points(value: Any) -> list[Any]:
    """A scalar stays one point; a time list is checked at every sample."""
    return list(value) if isinstance(value, list) else [value]


def read_tab_range(tab_path: Path | str) -> TabRange | None:
    """Read a table grid through the toolkit parser; None keeps today's behavior."""
    try:
        tab = Path(tab_path)
        if tab.suffix.casefold() != ".tab" or not tab.is_file():
            return None
        command = genkey_static.run_tool(
            "tab_parser", [str(tab), "--json"], names=fluids.FLUID_SCRIPTS
        )
        if command.exit_code != 0 or command.timed_out or not command.stdout.strip():
            return None
        parsed = json.loads(command.stdout)
        if not isinstance(parsed, dict):
            return None
        pressure = parsed.get("pressure_range") or {}
        temperature = parsed.get("temperature_range") or {}
        p_min = _number(pressure.get("min"))
        p_max = _number(pressure.get("max"))
        if p_min is None or p_max is None or p_min > p_max:
            return None
        t_min = _number(temperature.get("min"))
        t_max = _number(temperature.get("max"))
        if (t_min is None) != (t_max is None):
            return None
        if t_min is not None and t_max is not None and t_min > t_max:
            return None
        return TabRange(p_min, p_max, t_min, t_max, tab.name)
    except (OSError, ValueError, genkey_static.OlgaInputError):
        return None


def near_margin(quantity: str, edge: str, low: float, high: float) -> float:
    """How close to an edge a value may sit before it warns.

    10 percent of the axis span; on the pressure minimum it is also capped at
    half the minimum itself, so 1 atm on a 0.5-20 bar table does not warn.
    """
    margin = NEAR_FRACTION * (high - low)
    if quantity == "pressure" and edge == "minimum":
        margin = min(margin, 0.5 * abs(low))
    return margin


def classify(value: float, low: float, high: float, quantity: str) -> tuple[Status, str]:
    """Rank a value against one grid axis; the edge names the nearer bound."""
    if value < low - _edge_eps(low):
        return "outside", "minimum"
    if value > high + _edge_eps(high):
        return "outside", "maximum"
    if high - low <= 0:
        return "inside", "minimum"
    if value - low < near_margin(quantity, "minimum", low, high):
        return "near", "minimum"
    if high - value < near_margin(quantity, "maximum", low, high):
        return "near", "maximum"
    return "inside", "minimum"


def _fmt_bar(pascal: float) -> str:
    return f"{pascal / 100_000.0:g} bar"


def _fmt_c(celsius: float) -> str:
    return f"{celsius:g} C"


def _range_text(tab_range: TabRange) -> tuple[str, str]:
    """Pressure and temperature grid extents; English first, then Korean."""
    lo_bar = f"{tab_range.p_min_pa / 100_000.0:g}"
    hi_bar = f"{tab_range.p_max_pa / 100_000.0:g}"
    pressure_en = f"{lo_bar} bar to {hi_bar} bar"
    pressure_ko = f"{lo_bar}에서 {hi_bar} bar까지"
    if tab_range.t_min_c is None or tab_range.t_max_c is None:
        return pressure_en, pressure_ko
    temps_en = f"{tab_range.t_min_c:g} C to {tab_range.t_max_c:g} C"
    temps_ko = f"{tab_range.t_min_c:g}에서 {tab_range.t_max_c:g} C까지"
    return f"{pressure_en} and {temps_en}", f"{pressure_ko}, {temps_ko}"


def _headlines(quantity: str, relation: str) -> tuple[str, str]:
    axis = "PRESSURE" if quantity == "pressure" else "TEMPERATURE"
    direction = "BELOW" if relation == "below" else "ABOVE"
    return f"{axis} {direction} TABLE VALUES", "표 범위 이탈"


def _kind_word(kind: str) -> tuple[str, str]:
    return ("node", "노드") if kind == "node" else ("source", "소스")


def _axis_word(quantity: str) -> tuple[str, str]:
    return ("pressure", "압력") if quantity == "pressure" else ("temperature", "온도")


def _relation_word(relation: str) -> tuple[tuple[str, str], tuple[str, str]]:
    if relation == "below":
        return (("is below", "보다 낮습니다"), ("minimum", "최소값"))
    return (("is above", "보다 높습니다"), ("maximum", "최대값"))


def refusal_message(entry: RangeEntry, relation: str, tab_range: TabRange) -> str:
    """One definite pre-launch refusal naming the node, the value and the grid."""
    headline_en, headline_ko = _headlines(entry.quantity, relation)
    kind_en, kind_ko = _kind_word(entry.kind)
    axis_en, axis_ko = _axis_word(entry.quantity)
    (verb_en, verb_ko), (edge_en, edge_ko) = _relation_word(relation)
    if entry.quantity == "pressure":
        bound_pa = tab_range.p_min_pa if relation == "below" else tab_range.p_max_pa
        edge_text = _fmt_bar(bound_pa)
    else:
        bound_c = tab_range.t_min_c if relation == "below" else tab_range.t_max_c
        edge_text = _fmt_c(bound_c if bound_c is not None else entry.value_si)
    range_en, range_ko = _range_text(tab_range)
    english = (
        f"{headline_en}: {kind_en} {entry.origin} {axis_en} {entry.display} "
        f"{verb_en} the PVT table {edge_en} {edge_text} "
        f"(table {tab_range.tab} range {range_en}). "
        "Widen the table grid before launch."
    )
    korean = (
        f"{headline_ko}: {kind_ko} {entry.origin}의 {axis_ko} {entry.display}가 "
        f"PVT 표 {edge_ko} {edge_text}{verb_ko} "
        f"(표 {tab_range.tab} 범위 {range_ko}). 표 격자를 넓힌 뒤 실행하세요."
    )
    return f"{english} {korean}"


def warning_message(entry: RangeEntry, edge: str, tab_range: TabRange) -> str:
    """A near-edge value warns but never blocks; transients may leave the grid."""
    kind_en, kind_ko = _kind_word(entry.kind)
    axis_en, axis_ko = _axis_word(entry.quantity)
    edge_en = "minimum" if edge == "minimum" else "maximum"
    edge_ko = "최소값" if edge == "minimum" else "최대값"
    if entry.quantity == "pressure":
        low, high = tab_range.p_min_pa, tab_range.p_max_pa
        edge_text = _fmt_bar(low if edge == "minimum" else high)
        margin_text = _fmt_bar(near_margin("pressure", edge, low, high))
    else:
        bound = tab_range.t_min_c if edge == "minimum" else tab_range.t_max_c
        edge_text = _fmt_c(bound if bound is not None else entry.value_si)
        low, high = tab_range.t_min_c or 0.0, tab_range.t_max_c or 0.0
        margin_text = _fmt_c(near_margin("temperature", edge, low, high))
    range_en, range_ko = _range_text(tab_range)
    english = (
        f"Near the PVT table edge: {kind_en} {entry.origin} {axis_en} {entry.display} "
        f"is within {margin_text} of the table {edge_en} {edge_text} "
        f"(table {tab_range.tab} range {range_en}). "
        "Transients may leave the table; widen the grid."
    )
    korean = (
        f"표 경계 근처: {kind_ko} {entry.origin}의 {axis_ko} {entry.display}가 "
        f"표 {edge_ko} {edge_text}에서 {margin_text} 이내에 있습니다 "
        f"(표 {tab_range.tab} 범위 {range_ko}). "
        "천이 상태에서 표 범위를 벗어날 수 있습니다. 격자를 넓히세요."
    )
    return f"{english} {korean}"


def check_entries(
    entries: list[RangeEntry], tab_range: TabRange
) -> tuple[list[tuple[RangeEntry, str]], list[tuple[RangeEntry, str]]]:
    """Compare already-converted values; returns ((entry, refusal)), ((entry, warning))."""
    ordered = sorted(entries, key=lambda item: (item.origin, item.quantity, item.value_si))
    refusals: list[tuple[RangeEntry, str]] = []
    warnings: list[tuple[RangeEntry, str]] = []
    for entry in ordered:
        if entry.quantity == "pressure":
            low, high = tab_range.p_min_pa, tab_range.p_max_pa
        elif tab_range.t_min_c is None or tab_range.t_max_c is None:
            continue
        else:
            low, high = tab_range.t_min_c, tab_range.t_max_c
        status, edge = classify(entry.value_si, low, high, entry.quantity)
        if status == "outside":
            relation = "below" if entry.value_si < low - _edge_eps(low) else "above"
            refusals.append((entry, refusal_message(entry, relation, tab_range)))
        elif status == "near":
            warnings.append((entry, warning_message(entry, edge, tab_range)))
    return refusals, warnings


def _genkey_entries(parsed: Mapping[str, Any]) -> tuple[str | None, list[RangeEntry]]:
    """Boundary and source values from toolkit parser JSON; None skips safely."""
    try:
        globals_ = parsed.get("global_keywords")
        files = globals_.get("FILES") if isinstance(globals_, Mapping) else None
        raw_reference = files.get("PVTFILE") if isinstance(files, Mapping) else None
        if isinstance(raw_reference, Mapping):
            raw_reference = raw_reference.get("value")
        reference = raw_reference if isinstance(raw_reference, str) and raw_reference.strip() else None
        entries: list[RangeEntry] = []
        for node in parsed.get("nodes", []) or []:
            if not isinstance(node, Mapping):
                continue
            tag = node.get("tag")
            if not isinstance(tag, str) or not tag:
                continue
            for child in node.get("children", []) or []:
                if not isinstance(child, Mapping) or not _same_text(child.get("keyword"), "PARAMETERS"):
                    continue
                params = child.get("params")
                if not isinstance(params, Mapping) or not _same_text(_lookup(params, "TYPE"), "PRESSURE"):
                    continue
                pressure, pressure_unit = _scalar(params, "PRESSURE")
                pressure_text = pressure_unit if pressure_unit is not None else "Pa"
                for value in _points(pressure):
                    pascal = pressure_to_pa(value, pressure_text)
                    if pascal is None:
                        continue
                    display = f"{value:g} {pressure_text}"
                    entries.append(RangeEntry(tag, "node", "pressure", pascal, display, f"nodes.{tag}"))
                temperature, temperature_unit = _scalar(params, "TEMPERATURE")
                temperature_text = temperature_unit if temperature_unit is not None else "C"
                for value in _points(temperature):
                    celsius = temperature_to_c(value, temperature_text)
                    if celsius is None:
                        continue
                    display = f"{value:g} {temperature_text}"
                    entries.append(RangeEntry(tag, "node", "temperature", celsius, display, f"nodes.{tag}"))
        for flowpath in parsed.get("flowpaths", []) or []:
            if not isinstance(flowpath, Mapping):
                continue
            for child in flowpath.get("children", []) or []:
                if not isinstance(child, Mapping) or not _same_text(child.get("keyword"), "SOURCE"):
                    continue
                params = child.get("params")
                if not isinstance(params, Mapping):
                    continue
                label = _lookup(params, "LABEL")
                origin = label if isinstance(label, str) and label else str(flowpath.get("tag") or "SOURCE")
                temperature, temperature_unit = _scalar(params, "TEMPERATURE")
                unit = temperature_unit if temperature_unit is not None else "C"
                for value in _points(temperature):
                    celsius = temperature_to_c(value, unit)
                    if celsius is None:
                        continue
                    display = f"{value:g} {unit}"
                    entries.append(RangeEntry(origin, "source", "temperature", celsius, display, f"sources.{origin}"))
        return reference, entries
    except (AttributeError, TypeError, ValueError):
        return None, []


def check_genkey_source(source: Path | str) -> tuple[list[str], list[str]]:
    """Refusals and warnings for one .genkey file; empty keeps today's behavior."""
    try:
        path = Path(source)
        command = genkey_static.run_tool("parser", [str(path), "--json", "--compact"])
        if command.exit_code != 0 or command.timed_out or not command.stdout.strip():
            return [], []
        parsed = json.loads(command.stdout)
        if not isinstance(parsed, dict):
            return [], []
        reference, entries = _genkey_entries(parsed)
        if reference is None or not entries:
            return [], []
        tab_range = _resolve_tab_range(path, reference)
        if tab_range is None:
            return [], []
        refusals, warnings = check_entries(entries, tab_range)
        return [message for _, message in refusals], [message for _, message in warnings]
    except (OSError, ValueError, genkey_static.OlgaInputError):
        return [], []


def _resolve_tab_range(path: Path, reference: str | None) -> TabRange | None:
    if not reference:
        return None
    candidate = Path(reference)
    tab = candidate if candidate.is_absolute() else (path.parent / candidate).resolve()
    return read_tab_range(tab)


def _flowpath_initial_pressures(parsed: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for flowpath in parsed.get("flowpaths", []) or []:
        if not isinstance(flowpath, Mapping):
            continue
        for child in flowpath.get("children", []) or []:
            if not isinstance(child, Mapping):
                continue
            if not _same_text(child.get("keyword"), "INITIALCONDITIONS"):
                continue
            params = child.get("params")
            if not isinstance(params, Mapping):
                continue
            magnitude, unit = _scalar(params, "PRESSURE")
            pascal = pressure_to_pa(magnitude, unit if unit is not None else "Pa")
            if pascal is not None:
                values.append(pascal)
    return values


def pressure_step_message(
    low_pa: float, high_pa: float, tab_range: TabRange | None, locale: str | None = None,
) -> str:
    """One warning for a large boundary/start pressure step, in `locale` (ko/en) or both."""
    factor = high_pa / low_pa if low_pa > 0 else float("inf")
    if tab_range is None:
        scope_en, scope_ko = "", ""
    else:
        range_en, range_ko = _range_text(tab_range)
        scope_en, scope_ko = f" (table {tab_range.tab} range {range_en})", f" (표 {tab_range.tab} 범위 {range_ko})"
    english = (
        "Large pressure step: boundary and start pressures span "
        f"{_fmt_bar(low_pa)} to {_fmt_bar(high_pa)} (a {factor:.1f}x step){scope_en}. "
        "Transients may leave the PVT table grid, and the step can also heat or cool "
        "the fluid out of the table's temperature range. This warns only; the run is still allowed."
    )
    korean = (
        "큰 압력 단계: 경계와 시작 압력이 "
        f"{_fmt_bar(low_pa)}에서 {_fmt_bar(high_pa)}까지 이어집니다 ({factor:.1f}배 단계){scope_ko}. "
        "천이 상태에서 PVT 표 범위를 벗어날 수 있고, 유체가 가열되거나 냉각되어 표의 온도 범위를 "
        "벗어날 수도 있습니다. 경고일 뿐이며 실행은 막지 않습니다."
    )
    if locale == "en":
        return english
    if locale == "ko":
        return korean
    return f"{english} {korean}"


def _inside_pressure_grid(value_pa: float, tab_range: TabRange) -> bool:
    status, _ = classify(value_pa, tab_range.p_min_pa, tab_range.p_max_pa, "pressure")
    return status == "inside"


def _narrow_temperature_grid(tab_range: TabRange) -> bool:
    if tab_range.t_min_c is None or tab_range.t_max_c is None:
        return False
    return tab_range.t_max_c - tab_range.t_min_c <= NARROW_TEMPERATURE_SPAN_C


def pressure_step_warnings(source: Path | str, locale: str | None = None) -> list[str]:
    """Warn when the boundary/start pressure step is large; never refuse.

    Warns when the step exceeds pipe_table_import.START_PRESSURE_RATIO, the
    same strict comparison the import warning uses, and the table cannot
    vouch for the transient: its range is unreadable, an extreme leaves the
    pressure grid, or its temperature span is NARROW_TEMPERATURE_SPAN_C or
    narrower. An unreadable case, or one with fewer than two known
    pressures, warns nothing: the approval reads exactly as before.
    """
    try:
        path = Path(source)
        command = genkey_static.run_tool("parser", [str(path), "--json", "--compact"])
        if command.exit_code != 0 or command.timed_out or not command.stdout.strip():
            return []
        parsed = json.loads(command.stdout)
        if not isinstance(parsed, dict):
            return []
        reference, entries = _genkey_entries(parsed)
        pressures = [entry.value_si for entry in entries if entry.quantity == "pressure"]
        pressures.extend(_flowpath_initial_pressures(parsed))
        if len(pressures) < 2:
            return []
        low_pa, high_pa = min(pressures), max(pressures)
        if low_pa <= 0 or high_pa <= pipe_table_import.START_PRESSURE_RATIO * low_pa:
            return []
        tab_range = _resolve_tab_range(path, reference)
        if (
            tab_range is not None
            and _inside_pressure_grid(low_pa, tab_range)
            and _inside_pressure_grid(high_pa, tab_range)
            and not _narrow_temperature_grid(tab_range)
        ):
            return []
        return [pressure_step_message(low_pa, high_pa, tab_range, locale)]
    except (OSError, ValueError, TypeError, AttributeError, genkey_static.OlgaInputError):
        return []


def check_casespec_reference(
    normalized: Mapping[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """CaseSpec values against its workspace table; empty keeps today's behavior."""
    try:
        reference = normalized.get("pvt_reference")
        if not isinstance(reference, str) or not reference.strip():
            return [], []
        tab = workspace.contained(reference)
        if not tab.is_file():
            return [], []
        return check_casespec_points(normalized, tab)
    except (OSError, ValueError, workspace.WorkspaceError):
        return [], []


def check_casespec_points(
    normalized: Mapping[str, Any], tab_path: Path | str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """CaseSpec boundary and source values against one table; schema-ready issues."""
    try:
        entries: list[RangeEntry] = []
        for node in normalized.get("nodes", []) or []:
            if not isinstance(node, Mapping) or node.get("kind") not in {"source", "sink"}:
                continue
            label = str(node.get("label"))
            pressure = _number(node.get("pressure_pa"))
            if pressure is not None:
                entries.append(RangeEntry(
                    label, "node", "pressure", pressure, _fmt_bar(pressure),
                    f"nodes.{label}.pressure_pa",
                ))
            temperature = _number(node.get("temperature_c"))
            if temperature is not None:
                entries.append(RangeEntry(
                    label, "node", "temperature", temperature, _fmt_c(temperature),
                    f"nodes.{label}.temperature_c",
                ))
        for origin in normalized.get("massflow_sources", []) or []:
            if not isinstance(origin, Mapping):
                continue
            label = str(origin.get("label"))
            field = f"massflow_sources.{label}.temperature_c"
            points: list[Any] = [origin.get("temperature_c")]
            series = origin.get("series") or []
            points.extend(point.get("temperature_c") for point in series if isinstance(point, Mapping))
            for temperature in points:
                celsius = _number(temperature)
                if celsius is None:
                    continue
                entries.append(RangeEntry(
                    label, "source", "temperature", celsius, _fmt_c(celsius), field
                ))
        if not entries:
            return [], []
        tab_range = read_tab_range(tab_path)
        if tab_range is None:
            return [], []
        refusals, warnings = check_entries(entries, tab_range)
        errors = [
            {
                "code": "pvt_range_outside",
                "field": entry.field,
                "message": message,
                "guidance": (
                    "Move the value inside the PVT table grid or widen the table grid. "
                    "Do not invent table data."
                ),
            }
            for entry, message in refusals
        ]
        issues = [
            {
                "code": "pvt_range_near_edge",
                "field": entry.field,
                "message": message,
                "guidance": (
                    "Transients may leave the table; widen the grid. "
                    "Do not invent table data."
                ),
            }
            for entry, message in warnings
        ]
        return errors, issues
    except (OSError, ValueError):
        return [], []
