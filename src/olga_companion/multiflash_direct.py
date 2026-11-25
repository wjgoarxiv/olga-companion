"""Make an OLGA .tab from an .mfl with the Multiflash engine installed alongside OLGA.

The .mfl is read for its composition and its ``table olga`` grid. The engine runs in a child process
(``multiflash_child``) and writes the table to a hidden file beside the .mfl. The table is checked
with the same validator a picked-up table gets, and only a valid table is moved into place under a
new name: nothing is overwritten and a failed run leaves nothing behind. When the .mfl has no table
command, a stated default grid is used and the result says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import fluid_provenance, fluid_table
from .fluid_table import FluidTableError

Engine = Callable[[dict[str, Any]], dict[str, Any]]

ENGINE_TIMEOUT_S = 900
WINDOWS_PYTHON_ENV = "OLGA_COMPANION_WINDOWS_PYTHON"

_TEMPERATURE_TO_K: dict[str, Callable[[float], float]] = {
    "K": lambda v: v,
    "degC": lambda v: v + 273.15,
    "degF": lambda v: (v - 32.0) * 5.0 / 9.0 + 273.15,
    "degR": lambda v: v * 5.0 / 9.0,
}
_ATM = 101_325.0
# Factor to Pa and gauge offset per Multiflash pressure unit (mfcmd p.84).
_PRESSURE_TO_PA: dict[str, tuple[float, float]] = {
    "Pa": (1.0, 0.0), "kPa": (1e3, 0.0), "Mpa": (1e6, 0.0), "bar": (1e5, 0.0), "barg": (1e5, _ATM),
    "atm": (_ATM, 0.0), "atmg": (_ATM, _ATM), "psi": (6_894.757293168, 0.0), "psig": (6_894.757293168, _ATM),
    "mmHg": (133.322387415, 0.0), "inwg": (249.08891, 0.0), "at": (98_066.5, 0.0), "atg": (98_066.5, _ATM),
}
DEFAULT_TEMPERATURES_C = [float(t) for t in range(-20, 151, 10)]
DEFAULT_PRESSURES_BARA = [0.5, 1, 2, 3, 5, 7.5, 10, 15, 20, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250, 300]

_LEADING_COMMENT = re.compile(r"(?m)^\s*#[^#]*#")
_TABLE = re.compile(r'\btable\s+olga\s+"([^"]*)"(.*?);\s*;', re.IGNORECASE | re.DOTALL)
_TABLE_COMMAND = re.compile(r"\btable\s+olga\b", re.IGNORECASE)
_UNITS = re.compile(r"\bunits\b(.*?);", re.IGNORECASE | re.DOTALL)
_COMPONENTS = re.compile(r"\bcomponents\s+(?:overwrite\s+)?(.*?);", re.IGNORECASE | re.DOTALL)
_COMPONENT_ENTRY = re.compile(r"(\d+)\s+([A-Za-z0-9][^\s;]*)")
_AMOUNTS = re.compile(r"(?im)^\s*amounts\s+([-+0-9.][^;]*);")
_HAWATER = re.compile(r"\bHAWATER\b", re.IGNORECASE)
_TITLE = re.compile(r'\btitle\s+"([^"]*)"', re.IGNORECASE)
_TEMPS = re.compile(r"\btemperatures\s+(.*?)(?:;|$)", re.IGNORECASE | re.DOTALL)
_PRESS = re.compile(r"\bpressures\s+(.*?)(?:;|$)", re.IGNORECASE | re.DOTALL)
_TAB_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_. -]{0,120}\.tab", re.IGNORECASE)


def _numbers(tokens: list[str], what: str) -> list[float]:
    try:
        return [float(token) for token in tokens]
    except ValueError as exc:
        raise FluidTableError(f"The .mfl {what} list has a value that is not a number.") from exc


def _unit_in(command: str, keyword: str) -> str | None:
    found = re.search(rf"\b{keyword}\s+(\S+)", command, re.IGNORECASE)
    return found.group(1) if found else None


def _grid(body: str, pattern: re.Pattern[str], default_unit: str, what: str) -> tuple[list[float], str]:
    found = pattern.search(body)
    if not found:
        raise FluidTableError(f"The .mfl table command has no {what} list.")
    tokens = found.group(1).split()
    unit = default_unit
    if tokens and not re.match(r"^[-+0-9.]", tokens[0]):
        unit = tokens.pop(0)
    return _numbers(tokens, what), unit


def _to_k(values: list[float], unit: str) -> list[float]:
    convert = _TEMPERATURE_TO_K[fluid_table.canonical_temperature_unit(unit)]
    return [convert(value) for value in values]


def _to_pa(values: list[float], unit: str) -> list[float]:
    factor, offset = _PRESSURE_TO_PA[fluid_table.canonical_pressure_unit(unit)]
    return [value * factor + offset for value in values]


def read_table_request(mfl_text: str) -> dict[str, Any]:
    """Composition and grid (SI) for the engine, read from the .mfl text."""
    text = _LEADING_COMMENT.sub(" ", mfl_text.replace("\r", ""))
    components_match = _COMPONENTS.search(text)
    components = [name for _, name in _COMPONENT_ENTRY.findall(components_match.group(1))] if components_match else []
    amounts = _AMOUNTS.findall(text)
    if not amounts:
        raise FluidTableError("The .mfl has no composition (an amounts line), so no table can be made from it.")
    moles = _numbers(amounts[-1].split(), "amounts")
    if components and len(moles) != len(components):
        raise FluidTableError(
            f"The .mfl lists {len(components)} components but {len(moles)} amounts; they must match."
        )
    if not moles or sum(moles) <= 0:
        raise FluidTableError("The .mfl composition is all zero, so no table can be made from it.")
    _refuse_repeated_components(components)

    table = _TABLE.search(text)
    if table is None:
        if _TABLE_COMMAND.search(text):
            raise FluidTableError(
                'The .mfl has a table olga command the app cannot read: it needs the file name in quotes and ; ; at its end.'
            )
        return {
            "components": components, "moles": moles, "label": None, "grid_source": "default", "ha_water": False,
            "temperatures_k": _to_k(DEFAULT_TEMPERATURES_C, "degC"),
            "pressures_pa": _to_pa([float(p) for p in DEFAULT_PRESSURES_BARA], "bar"),
        }
    temperature_unit, pressure_unit = "K", "Pa"
    for units in _UNITS.finditer(text[: table.start()]):
        temperature_unit = _unit_in(units.group(1), "temperature") or temperature_unit
        pressure_unit = _unit_in(units.group(1), "pressure") or pressure_unit
    body = table.group(2) + ";"
    temperatures, t_unit = _grid(body, _TEMPS, temperature_unit, "temperature")
    pressures, p_unit = _grid(body, _PRESS, pressure_unit, "pressure")
    title = _TITLE.search(body)
    return {
        "components": components, "moles": moles, "label": title.group(1).strip() if title else None,
        "grid_source": "mfl",
        # As in Multiflash, the high-accuracy water model is used only when the table command asks for it.
        "ha_water": bool(_HAWATER.search(re.sub(r'"[^"]*"', " ", table.group(2)))),
        "temperatures_k": fluid_table.validate_grid(_to_k(temperatures, t_unit), "temperature"),
        "pressures_pa": fluid_table.validate_grid(_to_pa(pressures, p_unit), "pressure"),
    }


def _refuse_repeated_components(components: list[str]) -> None:
    """The same databank component twice (by name or synonym) makes a wrong table."""
    try:
        lookup = fluid_table.databank_names()
    except Exception:  # noqa: BLE001 - no databank: compare as written
        lookup = {}
    seen: dict[str, str] = {}
    for name in components:
        canonical = lookup.get(name.upper(), name.upper())
        if canonical in seen:
            raise FluidTableError(
                f"The .mfl lists {seen[canonical]!r} and {name!r}, which are the same component; list it once."
            )
        seen[canonical] = name


def _plain_code(code: int) -> str:
    return f"Multiflash {'warning' if code < 0 else 'error'} {code}."


def explain_error(code: int, error_file: Path) -> str:
    """The engine's own title and explanation for an error code, from its mflash.err list."""
    try:
        raw = error_file.read_text(encoding="latin-1")
    except OSError:
        return _plain_code(code)
    lines = raw.splitlines() if "\n" in raw else [raw[i:i + 80] for i in range(0, len(raw), 80)]
    lines = [line.rstrip() for line in lines]
    for index, line in enumerate(lines):
        if re.fullmatch(rf"(?:Error|Warning):\s+{code}", line.strip()) and index >= 3:
            detail: list[str] = []
            for follow in range(index + 1, len(lines)):
                if follow + 1 < len(lines) and lines[follow + 1].startswith("Module:"):
                    break
                detail.append(lines[follow].strip())
            return " ".join([lines[index - 3].strip(), *[part for part in detail if part]])
    return _plain_code(code)


def _label_for(request: dict[str, Any], mfl: Path) -> str:
    for candidate in (request.get("label"), re.sub(r"[^A-Za-z0-9_]", "_", mfl.stem).upper()):
        if candidate:
            try:
                return fluid_table.validate_label(candidate)
            except FluidTableError:
                continue
    return "FLUID"


def _child_command(request_file: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--multiflash-table", request_file]
    child = str(Path(__file__).with_name("multiflash_child.py"))
    if os.name == "nt":
        return [sys.executable, "-I", child, request_file]
    python = os.environ.get(WINDOWS_PYTHON_ENV)
    if not python:
        raise FluidTableError("Making a table with Multiflash needs the Windows app.")
    return [python, "-I", fluid_table.multiflash_path(child), fluid_table.multiflash_path(request_file)]


def run_engine(request: dict[str, Any]) -> dict[str, Any]:
    """Run the engine child once; paths in the request are the engine's (Windows) form."""
    folder = Path(request["work_dir"])
    request_file = folder / f".{request['token']}.mfrequest.json"
    result_file = folder / f".{request['token']}.mfresult.json"
    payload = {**request, "result_path": fluid_table.multiflash_path(str(result_file))}
    try:
        request_file.write_text(json.dumps(payload), encoding="utf-8")
        try:
            completed = subprocess.run(  # noqa: S603
                _child_command(str(request_file)), capture_output=True, timeout=ENGINE_TIMEOUT_S, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise FluidTableError("Multiflash did not finish the table within 15 minutes.") from exc
        except OSError as exc:
            raise FluidTableError("The Multiflash engine could not be started.") from exc
        if not result_file.is_file():
            raise FluidTableError(
                f"The Multiflash engine stopped without an answer (exit {completed.returncode})."
            )
        return json.loads(result_file.read_text(encoding="utf-8"))
    finally:
        request_file.unlink(missing_ok=True)
        result_file.unlink(missing_ok=True)


def engine_available() -> str | None:
    """Why no table can be made on this PC, or None when the engine is ready to be tried."""
    discovery = fluid_table.find_multiflash()
    if not discovery.get("found"):
        return str(discovery.get("message") or "Multiflash was not found on this PC.")
    if os.name != "nt" and not os.environ.get(WINDOWS_PYTHON_ENV):
        return "Making a table with Multiflash needs Windows."
    return None


def make_tab(
    mfl_path: str,
    tab_name: str | None,
    *,
    engine: Engine | None = None,
    error_file: Path | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Write a new, validated .tab beside the .mfl; never overwrite and leave nothing on failure."""
    mfl = Path(mfl_path)
    name = tab_name if tab_name is not None else f"{mfl.stem}.tab"
    if not _TAB_NAME.fullmatch(name or "") or Path(name).name != name:
        raise FluidTableError("The table name must be a plain file name ending in .tab.")
    target = mfl.parent / name
    if target.exists():
        raise FluidTableError(f"{name} already exists next to the case; the app does not overwrite it.")
    try:
        mfl_bytes = mfl.read_bytes()
    except OSError as exc:
        raise FluidTableError(f"File not found: {mfl.name}") from exc
    if expected_sha256 is not None and hashlib.sha256(mfl_bytes).hexdigest() != expected_sha256:
        raise FluidTableError(f"{mfl.name} changed after the approval was asked for; nothing was made. Ask again.")
    mfl_text = mfl_bytes.decode("utf-8", errors="replace")
    request = read_table_request(mfl_text)
    label = _label_for(request, mfl)
    token = os.urandom(6).hex()
    partial = mfl.parent / f".{token}.making.tab"
    engine_dir = ""
    if engine is None:
        discovery = fluid_table.find_multiflash()
        if not discovery.get("found"):
            raise FluidTableError(str(discovery.get("message") or "Multiflash was not found on this PC."))
        engine_dir = str(Path(discovery["exe"]).parent)
        error_file = error_file or Path(engine_dir) / "mflash.err"
    job = {
        "engine_dir": fluid_table.multiflash_path(engine_dir) if engine_dir else "",
        "mfl_text": mfl_text, "moles": request["moles"], "title": label,
        "pressures_pa": request["pressures_pa"], "temperatures_k": request["temperatures_k"],
        "tab_path": str(partial) if engine is not None else fluid_table.multiflash_path(str(partial)),
        "work_dir": str(mfl.parent), "token": token, "ha_water": request["ha_water"],
    }
    try:
        outcome = (engine or run_engine)(job)
        table_codes = [int(code) for code in outcome.get("errors") or []]
        load_codes = [int(code) for code in outcome.get("load_errors") or []]
        # Multiflash numbers its warnings below zero: the table is written and the warning describes it.
        codes = [code for code in table_codes if code >= 0]
        if codes or (not outcome.get("ok") and not table_codes):
            reason = explain_error(codes[0], error_file) if codes and error_file else "the engine reported a failure"
            raise FluidTableError(f"Multiflash could not make the table (error {codes[0] if codes else '?'}): {reason}")
        load_failures = [code for code in load_codes if code >= 0]
        if load_failures:
            reason = explain_error(load_failures[0], error_file) if error_file else "the engine could not read the file"
            raise FluidTableError(f"Multiflash could not read {mfl.name} (error {load_failures[0]}): {reason}")
        engine_warnings = [
            explain_error(code, error_file) if error_file else _plain_code(code)
            for code in dict.fromkeys([*load_codes, *table_codes])
        ]
        if not partial.is_file() or partial.stat().st_size == 0:
            raise FluidTableError("Multiflash finished but wrote no table.")
        check = fluid_table.pickup_tab(str(partial), label)
        if not check.get("valid"):
            first = (check.get("errors") or [{}])[0]
            raise FluidTableError(f"Multiflash wrote a table that is not valid: {first.get('message', 'unknown problem')}")
        if target.exists():
            raise FluidTableError(f"{name} appeared while the table was being made; the app does not overwrite it.")
        partial.rename(target)
    finally:
        partial.unlink(missing_ok=True)
    result = fluid_table.pickup_tab(str(target), label)
    # The table is in place; a record that cannot be written makes it "unknown origin", not a failure.
    try:
        record_name: str | None = fluid_provenance.write_record(
            target,
            mfl=mfl,
            mfl_sha256=hashlib.sha256(mfl_bytes).hexdigest(),
            grid={"temperatures_k": request["temperatures_k"], "pressures_pa": request["pressures_pa"]},
            grid_source=request["grid_source"],
        ).name
    except OSError:
        record_name = None
    return {
        **result, "tab_name": name, "fluid_label": label, "grid_source": request["grid_source"],
        "hawater": request["ha_water"],
        "provenance": record_name, "engine_warnings": engine_warnings,
        **({} if record_name else {"provenance_error": "record_not_written"}),
        "points": {"pressures": len(request["pressures_pa"]), "temperatures": len(request["temperatures_k"])},
    }
