"""A STANDARD-format OLGA ``.tab`` from property values the user already has.

The user brings a long-form CSV or XLSX (one row per pressure and temperature
point) from HYSYS, PVTsim, a laboratory or any other source. This module only
re-formats it: every number is written as given, apart from the unit change of
the two axes to Pa and degC. Nothing is calculated, interpolated, filled or
corrected, and no thermodynamic engine is involved.

Columns
    One pressure column and one temperature column, each with its unit in the
    header: ``P (bar)``, ``Pressure [kPa]``, ``P_MPa``, ``psia``, ``T (C)``,
    ``Temperature (K)``, ``degF``. A pressure or temperature with no unit is
    refused, never guessed. Gauge units (barg, psig) add one standard
    atmosphere to reach absolute pressure.

    Every other column is a property named by its OLGA keyword (ROG, ROHL,
    VISG, VISHL, RS, CPG, CPHL, HG, HHL, TCG, TCHL, SIGGHL, ...). Its values are
    taken to be in the unit OLGA uses for that keyword (kg/m3, Ns/m2, J/kg/C,
    W/m/C, N/m, ...; the table is the toolkit validator's ``_KEYWORD_COLUMNS``).
    A header that states another unit is refused rather than rescaled.
    Columns that are not an OLGA keyword are listed and left out.

Grid
    The pressures and temperatures must each be strictly increasing in the
    order they first appear, every pressure/temperature pair must be present
    exactly once, and every number must be finite. A water-phase column
    (ROWT, VISWT, ...) makes the table PHASE = THREE, which also needs the total
    water fraction the user states; otherwise it is PHASE = TWO.

The text that is offered has been parsed back with the toolkit ``TabParser``
(every value compared) and checked with the toolkit validator. Previewing writes
nothing; writing is a separate step that never overwrites a file.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import fluid_table, tab_compare
from .pipe_table import (
    MAX_FILE_BYTES,
    PipeTableError,
    _OLE2_SIGNATURE,
    _csv_rows,
    _number,
    _xlsx_rows,
)

MAX_POINTS = 20_000
MAX_ISSUES = 50
MAX_COMPONENTS = 64
HEAD_LINES = 14
_HEADER_SCAN_ROWS = 50
_ATM_PA = 101_325.0
_PSI_PA = 6894.757293168
_COMPOSITION_TOLERANCE = 1e-6
_NO_COMPOSITION = "NOT_STATED"
KIND_EN = "Values written as given from your own table; nothing is calculated. Check that the units and the range fit your case."
KIND_KO = "내가 가진 표의 값을 그대로 옮겨 쓴 표입니다. 계산한 값은 없습니다. 단위와 범위가 내 사례에 맞는지 확인하세요."

_PRESSURE_NAMES = {"p", "pres", "press", "pressure"}
_TEMPERATURE_NAMES = {"t", "temp", "temperature"}
# unit -> (factor to Pa, offset in Pa added after scaling)
_PRESSURE_UNITS: dict[str, tuple[float, float]] = {
    "pa": (1.0, 0.0), "kpa": (1e3, 0.0), "mpa": (1e6, 0.0),
    "bar": (1e5, 0.0), "bara": (1e5, 0.0), "barg": (1e5, _ATM_PA),
    "psi": (_PSI_PA, 0.0), "psia": (_PSI_PA, 0.0), "psig": (_PSI_PA, _ATM_PA),
    "atm": (_ATM_PA, 0.0), "atma": (_ATM_PA, 0.0),
}
_TEMPERATURE_UNITS = {"c", "degc", "celsius", "k", "kelvin", "f", "degf", "r", "degr"}
_COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_ .+/#-]{0,63}")


class TabImportError(ValueError):
    """The request cannot be previewed or written at all (as opposed to a table with issues)."""

    def __init__(self, reason: str, code: str = "") -> None:
        super().__init__(reason)
        self.code = code


def olga_units() -> dict[str, tuple[str, str]]:
    """OLGA keyword -> (unit, role) for the property columns this module accepts."""
    _, validator = tab_compare._toolkit()
    return {
        code: spec for code, spec in validator._KEYWORD_COLUMNS.items() if spec[1] != "axis"
    }


def _unit_key(unit: str) -> str:
    return unit.lower().replace("°", "").replace(" ", "").replace("³", "3").replace("^", "").replace("·", "")


def _same_unit(found: str, expected: str) -> bool:
    return _unit_key(found).replace("*", "") == _unit_key(expected)


@dataclass(frozen=True)
class _Column:
    index: int
    header: str
    kind: str  # pressure | temperature | property | ignored
    unit: str = ""
    code: str = ""


def _issue(code: str, reason: str, row: int | None = None, **params: Any) -> dict[str, Any]:
    return {"code": code, "row": row, "reason": reason, "params": params}


def _split_header(text: str) -> tuple[str, str | None]:
    bracket = re.fullmatch(r"(.+?)\s*[(\[]\s*(.*?)\s*[)\]]", text)
    if bracket:
        return bracket.group(1).strip(), bracket.group(2).strip()
    suffixed = re.fullmatch(r"([A-Za-z]+)[_\s]+(\S+)", text)
    if suffixed and suffixed.group(1).lower() in _PRESSURE_NAMES | _TEMPERATURE_NAMES:
        return suffixed.group(1), suffixed.group(2)
    return text, None


def _classify(index: int, raw: object, properties: dict[str, tuple[str, str]]) -> _Column:
    header = str(raw).strip()
    if not header:
        return _Column(index, header, "ignored")
    name, unit = _split_header(header)
    lowered = name.lower()
    if lowered in _PRESSURE_NAMES:
        return _Column(index, header, "pressure", unit or "")
    if lowered in _TEMPERATURE_NAMES:
        return _Column(index, header, "temperature", unit or "")
    if lowered == "pt":
        return _Column(index, header, "pressure", unit or "Pa")
    if lowered == "tm":
        return _Column(index, header, "temperature", unit or "C")
    if unit is None and _unit_key(name) in _PRESSURE_UNITS:
        return _Column(index, header, "pressure", name)
    if unit is None and _unit_key(name) in _TEMPERATURE_UNITS:
        return _Column(index, header, "temperature", name)
    if name.upper() in properties:
        return _Column(index, header, "property", unit or "", name.upper())
    return _Column(index, header, "ignored")


def _read_rows(source: Path, sheet: str | None) -> tuple[list[list[object]], set[tuple[int, int]], str | None]:
    """The raw rows of a CSV or XLSX, with the same size, encryption and archive limits as pipe tables."""
    suffix = source.suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise TabImportError("A property table must be a .csv or .xlsx file.", "table_suffix")
    try:
        if source.stat().st_size > MAX_FILE_BYTES:
            raise TabImportError("The table file is larger than 20 MiB.", "table_too_large")
        with source.open("rb") as handle:
            magic = handle.read(16)
    except OSError as exc:
        raise TabImportError(f"The table could not be read: {exc.strerror or type(exc).__name__}.", "table_unreadable") from exc
    if magic[:8] == _OLE2_SIGNATURE or (suffix == ".xlsx" and b"DRM" in magic and not magic.startswith(b"PK\x03\x04")):
        raise TabImportError("The file is protected (encrypted or DRM); save an unprotected copy.", "table_encrypted")
    try:
        if suffix == ".csv":
            return _csv_rows(source), set(), None
        return _xlsx_rows(source, sheet)
    except PipeTableError as exc:
        raise TabImportError(str(exc), "table_unreadable") from exc
    except Exception as exc:  # noqa: BLE001 - a damaged archive or stream is a refusal, never a crash
        raise TabImportError(f"The table could not be read ({type(exc).__name__}).", "table_unreadable") from exc


def _find_header(
    rows: list[list[object]], properties: dict[str, tuple[str, str]]
) -> tuple[int, list[_Column]] | None:
    for index, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        columns = [_classify(position, value, properties) for position, value in enumerate(row)]
        kinds = {column.kind for column in columns}
        if "pressure" in kinds and "temperature" in kinds:
            return index, columns
    return None


def _pressure_to_pa(value: float, unit: str) -> float:
    factor, offset = _PRESSURE_UNITS[_unit_key(unit)]
    return value * factor + offset


def _temperature_to_c(value: float, unit: str) -> float:
    key = _unit_key(unit)
    if key in {"k", "kelvin"}:
        return value - 273.15
    if key in {"f", "degf"}:
        return (value - 32.0) * 5.0 / 9.0
    if key in {"r", "degr"}:
        return value * 5.0 / 9.0 - 273.15
    return value


def _axis(value: float) -> float:
    """The axis value as it will be written, so the file and the check use the same number."""
    return float(f"{value:.10g}")


def _axis_text(value: float) -> str:
    return f"{value:.10g}"


def _value_text(value: float) -> str:
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text


def _header_issues(columns: list[_Column], properties: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for kind, missing_code in (("pressure", "pressure_unit_missing"), ("temperature", "temperature_unit_missing")):
        chosen = [column for column in columns if column.kind == kind]
        if len(chosen) > 1:
            issues.append(_issue(
                "duplicate_axis_column",
                f"More than one {kind} column ({', '.join(c.header for c in chosen)}); keep one.",
                axis=kind, columns=[c.header for c in chosen],
            ))
            continue
        column = chosen[0]
        known = _PRESSURE_UNITS if kind == "pressure" else {u: None for u in _TEMPERATURE_UNITS}
        if not column.unit:
            issues.append(_issue(
                missing_code,
                f"State the {kind} unit in the header of {column.header!r} (for example "
                f"{'P (bar)' if kind == 'pressure' else 'T (C)'}).",
                column=column.header,
            ))
        elif _unit_key(column.unit) not in known:
            issues.append(_issue(
                f"{kind}_unit_unknown",
                f"Unknown {kind} unit {column.unit!r} in {column.header!r}.",
                column=column.header, unit=column.unit[:48],
            ))
    seen: set[str] = set()
    for column in columns:
        if column.kind != "property":
            continue
        if column.code in seen:
            issues.append(_issue("duplicate_column", f"Column {column.code} appears twice.", column=column.code))
        seen.add(column.code)
        expected = properties[column.code][0]
        if column.unit and not _same_unit(column.unit, expected):
            issues.append(_issue(
                "property_unit_mismatch",
                f"{column.header!r} states {column.unit}; OLGA takes {column.code} in {expected}. "
                "Convert the column first: values are never rescaled here.",
                column=column.code, unit=column.unit[:48], expected=expected,
            ))
    return issues


def _clean_composition(
    components: Sequence[str] | None, moles: Sequence[float] | None
) -> tuple[list[str], list[float], dict[str, Any] | None]:
    if components is None and moles is None:
        return [_NO_COMPOSITION], [1.0], None
    names = [str(item).strip() for item in (components or [])]
    fractions = list(moles or [])
    problem = None
    if not names or len(names) != len(fractions) or len(names) > MAX_COMPONENTS:
        problem = "COMPONENTS and MOLES must be given together, with the same count (at most 64)."
    elif any(_COMPONENT.fullmatch(name) is None for name in names):
        problem = "A component name may use letters, digits and _ . + / # - only."
    elif any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in fractions):
        problem = "Mole fractions must be finite numbers of at least 0."
    elif abs(sum(fractions) - 1.0) > _COMPOSITION_TOLERANCE:
        problem = f"Mole fractions must sum to 1 (they sum to {sum(fractions):.6g})."
    if problem is not None:
        return [], [], _issue("composition_invalid", problem)
    return names, [float(x) for x in fractions], None


def _render(
    *,
    label: str,
    phase: str,
    components: list[str],
    moles: list[float],
    water_fraction: float | None,
    pressures: list[float],
    temperatures: list[float],
    columns: list[str],
    values: dict[tuple[float, float], list[float]],
) -> str:
    names = ", ".join(f'"{name}"' for name in components)
    fractions = ", ".join(_value_text(x) for x in moles)
    header = [
        f'PVTTABLE LABEL = "{label}",PHASE = {phase}, \\',
        f"COMPONENTS = ( {names} ), MOLES = ( {fractions} ), \\",
        "MESHTYPE = STANDARD, \\",
    ]
    if phase == "THREE":
        header.append(f"TOTWATERFRACTION = ( {_value_text(water_fraction or 0.0)} ), \\")
    header += [
        f"PRESSURE = ( {', '.join(_axis_text(p) for p in pressures)} ) PA, \\",
        f"TEMPERATURE = ( {', '.join(_axis_text(t) for t in temperatures)} ) C, \\",
        f"COLUMNS = ( {', '.join(['PT', 'TM', *columns])} )",
    ]
    points = [
        f"PVTTABLE POINT = ( {_axis_text(p)}, {_axis_text(t)}, "
        + ", ".join(_value_text(v) for v in values[(p, t)]) + " )"
        for p in pressures for t in temperatures
    ]
    note = "! Written as given from the user's own table; no property was calculated."
    return "\n".join([*header, *points, note]) + "\n"


def _round_trip(
    text: str, *, label: str, phase: str, pressures: list[float], temperatures: list[float],
    columns: list[str], values: dict[tuple[float, float], list[float]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Parse the text with the toolkit parser and compare every value; then run the validator."""
    with tempfile.TemporaryDirectory(prefix="olga-tab-import-") as scratch:
        path = Path(scratch) / "check.tab"
        path.write_text(text, encoding="utf-8")
        try:
            parsed = tab_compare._parse(path)
            problem = None
            rows = parsed.point_rows or []
            if parsed.label.strip('"') != label or parsed.phase.upper() != phase:
                problem = "the label or the phase did not survive the round trip"
            elif list(parsed.pressure_grid) != pressures or list(parsed.temperature_grid) != temperatures:
                problem = "the pressure or temperature grid did not survive the round trip"
            elif list(parsed.columns) != ["PT", "TM", *columns]:
                problem = "the column list did not survive the round trip"
            elif len(rows) != len(pressures) * len(temperatures):
                problem = "the table does not hold every grid point"
            else:
                expected = [[p, t, *values[(p, t)]] for p in pressures for t in temperatures]
                if sorted(map(list, rows)) != sorted(expected):
                    problem = "a value changed in the round trip"
        except (ValueError, LookupError, OSError) as exc:
            problem = f"the toolkit parser rejected the table ({exc})"
        if problem is not None:
            return [_issue("roundtrip_failed", f"The table was not offered: {problem}.")], [], {}
        try:
            report = tab_compare._validate(path)
        except (ValueError, LookupError, OSError) as exc:
            return [_issue("roundtrip_failed", f"The toolkit validator could not check the table ({exc}).")], [], {}
    errors = [
        _issue("validator_error", f"{item.get('rule_id', '')}: {item.get('message', '')}".strip(": "),
               rule=item.get("rule_id", ""))
        for item in report.get("errors", [])
    ]
    warnings = [
        _issue("validator_warning", f"{item.get('rule_id', '')}: {item.get('message', '')}".strip(": "),
               rule=item.get("rule_id", ""))
        for item in report.get("warnings", [])
    ]
    return errors, warnings, {"validator_errors": len(errors), "validator_warnings": len(warnings)}


def build(
    source: Path | str,
    *,
    fluid_label: str,
    sheet: str | None = None,
    components: Sequence[str] | None = None,
    moles: Sequence[float] | None = None,
    total_water_fraction: float | None = None,
) -> dict[str, Any]:
    """Read the table and build the ``.tab`` text, or say what is wrong. Reads only; writes nothing.

    Returns ``ok``, ``issues`` (blocking), ``warnings``, ``summary`` and ``text`` (None unless ``ok``).
    A request that cannot be read at all raises ``TabImportError``; a bad label raises ``FluidTableError``.
    """
    label = fluid_table.validate_label(fluid_label)
    source = Path(source)
    rows, missing_cache, sheet_name = _read_rows(source, sheet)
    properties = olga_units()
    summary: dict[str, Any] = {
        "fluid_label": label, "source": source.name, "sheet": sheet_name, "calculated": False,
        "pressure_points": 0, "temperature_points": 0, "points": 0, "columns": [],
        "ignored_columns": [], "phase": None, "source_units": {},
        "components_stated": components is not None,
    }
    issues: list[dict[str, Any]] = []

    def result(text: str | None = None, warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        blocking = issues[:MAX_ISSUES]
        ok = text is not None and not issues
        return {
            "ok": ok, "issues": blocking, "issue_count": len(issues), "warnings": (warnings or [])[:MAX_ISSUES],
            "summary": summary, "text": text if ok else None,
            "tab_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if ok and text else None,
            "tab_bytes": len(text.encode("utf-8")) if ok and text else 0,
        }

    found = _find_header(rows, properties)
    if found is None:
        issues.append(_issue(
            "header_not_found",
            "No header row with a pressure column and a temperature column was found "
            "(for example P (bar), T (C), ROG, ROHL).",
        ))
        return result()
    header_index, all_columns = found
    columns = [column for column in all_columns if column.kind != "ignored" or column.header]
    summary["ignored_columns"] = [column.header for column in columns if column.kind == "ignored"]
    used = [column for column in columns if column.kind != "ignored"]
    issues.extend(_header_issues(used, properties))
    p_col = next(column for column in used if column.kind == "pressure")
    t_col = next(column for column in used if column.kind == "temperature")
    props = [column for column in used if column.kind == "property"]
    summary["columns"] = [column.code for column in props]
    summary["source_units"] = {"pressure": p_col.unit, "temperature": t_col.unit}

    codes = [column.code for column in props]
    water = any(properties[code][1] == "water" for code in codes)
    phase = "THREE" if water else "TWO"
    summary["phase"] = phase
    required = ["ROG", "ROHL", *(["ROWT"] if water else [])]
    absent = [code for code in required if code not in codes]
    if absent:
        issues.append(_issue(
            "required_column_missing",
            f"The table needs the column(s) {', '.join(absent)} (OLGA requires them for PHASE = {phase}).",
            columns=absent, phase=phase,
        ))
    fraction: float | None = None
    if water:
        if isinstance(total_water_fraction, bool) or not isinstance(total_water_fraction, (int, float)):
            issues.append(_issue(
                "water_fraction_required",
                "A water-phase column makes this a three-phase table; state the total water fraction (0 to 1).",
            ))
        elif not math.isfinite(total_water_fraction) or not 0 <= total_water_fraction <= 1:
            issues.append(_issue("water_fraction_invalid", "The total water fraction must be between 0 and 1."))
        else:
            fraction = float(total_water_fraction)
    names, fractions, composition_issue = _clean_composition(components, moles)
    if composition_issue is not None:
        issues.append(composition_issue)

    if any(issue["code"] in {"duplicate_axis_column", "pressure_unit_missing", "temperature_unit_missing",
                              "pressure_unit_unknown", "temperature_unit_unknown"} for issue in issues):
        return result()

    values: dict[tuple[float, float], list[float]] = {}
    pressures: list[float] = []
    temperatures: list[float] = []
    cell_problems = 0
    duplicates = 0
    for row_index in range(header_index + 1, len(rows)):
        row = rows[row_index]
        if not any(str(value).strip() for value in row):
            continue
        number = row_index + 1
        cells: dict[int, float] = {}
        for column in (p_col, t_col, *props):
            raw = row[column.index] if column.index < len(row) else ""
            name = column.code or column.header
            if (row_index, column.index) in missing_cache:
                cell_problems += 1
                if len(issues) < MAX_ISSUES:
                    issues.append(_issue("formula_no_cached", f"Row {number}, {name}: a formula without a saved value; save the file in Excel first.", number, column=name))
                continue
            if str(raw).strip() == "":
                cell_problems += 1
                if len(issues) < MAX_ISSUES:
                    issues.append(_issue("missing_value", f"Row {number}, {name}: the cell is empty.", number, column=name))
                continue
            parsed = _number(raw)
            if parsed is None or not math.isfinite(parsed):
                cell_problems += 1
                if len(issues) < MAX_ISSUES:
                    issues.append(_issue("not_a_number", f"Row {number}, {name}: {str(raw).strip()[:24]!r} is not a finite number.", number, column=name))
                continue
            cells[column.index] = parsed
        if len(cells) != 2 + len(props):
            continue
        pressure = _axis(_pressure_to_pa(cells[p_col.index], p_col.unit))
        temperature = _axis(_temperature_to_c(cells[t_col.index], t_col.unit))
        if pressure <= 0:
            cell_problems += 1
            if len(issues) < MAX_ISSUES:
                issues.append(_issue("pressure_not_positive", f"Row {number}: the absolute pressure must be above 0 Pa.", number))
            continue
        key = (pressure, temperature)
        if key in values:
            duplicates += 1
            if len(issues) < MAX_ISSUES:
                issues.append(_issue("duplicate_point", f"Row {number}: the point {pressure:g} Pa, {temperature:g} C appears twice.", number, pressure_pa=pressure, temperature_c=temperature))
            continue
        values[key] = [cells[column.index] for column in props]
        if pressure not in pressures:
            pressures.append(pressure)
        if temperature not in temperatures:
            temperatures.append(temperature)

    summary["pressure_points"], summary["temperature_points"] = len(pressures), len(temperatures)
    summary["points"] = len(values)
    if pressures:
        summary["pressure_range_pa"] = [min(pressures), max(pressures)]
    if temperatures:
        summary["temperature_range_c"] = [min(temperatures), max(temperatures)]
    if cell_problems or duplicates:
        return result()
    if len(pressures) < 2 or len(temperatures) < 2:
        issues.append(_issue(
            "grid_too_small", "A table needs at least two pressures and two temperatures.",
            pressures=len(pressures), temperatures=len(temperatures),
        ))
        return result()
    axis_problem = False
    for axis, axis_values in (("pressure", pressures), ("temperature", temperatures)):
        if any(a >= b for a, b in zip(axis_values, axis_values[1:])):
            axis_problem = True
            issues.append(_issue(
                "axis_not_increasing",
                f"The {axis} values must increase down the table; sort the rows by {axis} first.",
                axis=axis,
            ))
    if axis_problem:
        return result()
    if len(pressures) * len(temperatures) > MAX_POINTS:
        issues.append(_issue("grid_too_large", f"A grid holds at most {MAX_POINTS} points.", limit=MAX_POINTS))
        return result()
    lacking = [(p, t) for p in pressures for t in temperatures if (p, t) not in values]
    if lacking:
        issues.append(_issue(
            "missing_point",
            f"{len(lacking)} pressure/temperature point(s) are missing; the first is {lacking[0][0]:g} Pa, {lacking[0][1]:g} C.",
            count=len(lacking), first=[lacking[0][0], lacking[0][1]],
        ))
        return result()
    if issues:
        return result()

    text = _render(
        label=label, phase=phase, components=names, moles=fractions, water_fraction=fraction,
        pressures=pressures, temperatures=temperatures, columns=codes, values=values,
    )
    errors, warnings, counts = _round_trip(
        text, label=label, phase=phase, pressures=pressures, temperatures=temperatures,
        columns=codes, values=values,
    )
    summary.update(counts)
    issues.extend(errors)
    return result(text, warnings)


def build_request(source: Path | str, request: Mapping[str, Any]) -> dict[str, Any]:
    """``build`` for a stored request (the approval payload): the optional fields may be absent or None."""
    return build(
        source,
        fluid_label=request["fluid_label"],
        sheet=request.get("sheet"),
        components=request.get("components"),
        moles=request.get("moles"),
        total_water_fraction=request.get("total_water_fraction"),
    )


def preview(source: Path | str, **options: Any) -> dict[str, Any]:
    """What the user sees before any approval: the summary, the issues and the first lines of the file."""
    built = build(source, **options)
    text = built.pop("text")
    built["text_head"] = None if text is None else "\n".join(text.splitlines()[:HEAD_LINES])
    built["writes_nothing"] = True
    return built


def write_new(destination: Path, text: str) -> None:
    """Create ``destination`` with ``text``; an existing file is never touched."""
    try:
        with open(destination, "xb") as stream:
            stream.write(text.encode("utf-8"))
    except FileExistsError as exc:
        raise TabImportError(
            f"{destination.name} already exists; choose a new table name. Nothing is ever overwritten.",
            "destination_exists",
        ) from exc
