"""Bounded temporary-file verification for deterministic CaseSpec compilation."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from . import genkey_static

# Rows are (flowpath, pipe, start, end, diameter, nsegment, lsegment) for centerline
# pipes and (flowpath, pipe, "length", length, elevation, diameter, nsegment, lsegment)
# for length/elevation pipes; one case uses one form.
Geometry: TypeAlias = tuple[tuple[Any, ...], ...]


@dataclass(frozen=True)
class ToolkitVerification:
    clean: bool
    parser_clean: bool
    validator_clean: bool
    diagnostics: tuple[str, ...]
    topology_edges: tuple[tuple[str, str, str], ...] = ()
    section_count: int = 0
    junction_terminals: tuple[tuple[str, str, str, str], ...] = ()
    geometry: Geometry = ()
    pvt_reference: str = ""
    end_time_s: float = 0.0
    outputs: tuple[str, ...] = ()
    fluid_labels: tuple[str, ...] = ()
    thermal: tuple[Any, ...] = ()
    boundaries: tuple[tuple[str, float, float], ...] = ()
    roughness: tuple[tuple[str, str, float], ...] = ()


def _number(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value")
    return float(value)


def _seconds(value: Any) -> float:
    if not isinstance(value, dict):
        return float(value)
    factors = {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0, "d": 86_400.0}
    unit = str(value.get("unit") or "s").casefold()
    if unit not in factors:
        raise ValueError(f"unsupported ENDTIME unit: {unit}")
    magnitude = value.get("value")
    if not isinstance(magnitude, (int, float, str)) or isinstance(magnitude, bool):
        raise ValueError("ENDTIME magnitude is not numeric")
    return float(magnitude) * factors[unit]


def _values(value: Any) -> tuple[float, ...]:
    if isinstance(value, dict):
        value = value.get("value")
    values = value if isinstance(value, list) else [value]
    return tuple(float(item) for item in values)


def _geometry(parsed: dict[str, Any]) -> Geometry:
    rows: list[Any] = []
    for flowpath in parsed.get("flowpaths", []):
        children = flowpath.get("children", [])
        geometry = next(item["params"] for item in children if item.get("keyword") == "GEOMETRY")
        if "XSTART" not in geometry:
            # Length/elevation pipes (CaseSpec v3) carry no coordinates.
            rows.extend(
                (
                    flowpath["tag"], str(child["params"]["LABEL"]), "length",
                    _number(child["params"]["LENGTH"]), _number(child["params"]["ELEVATION"]),
                    _number(child["params"]["DIAMETER"]), int(child["params"]["NSEGMENT"]),
                    _values(child["params"]["LSEGMENT"]),
                )
                for child in children
                if child.get("keyword") == "PIPE"
            )
            continue
        start = (
            _number(geometry["XSTART"]),
            _number(geometry["YSTART"]),
            _number(geometry["ZSTART"]),
        )
        for child in children:
            if child.get("keyword") != "PIPE":
                continue
            params = child["params"]
            end = (
                _number(params["XEND"]),
                _number(params["YEND"]),
                _number(params["ZEND"]),
            )
            rows.append((
                flowpath["tag"], str(params["LABEL"]), start, end,
                _number(params["DIAMETER"]), int(params["NSEGMENT"]), _values(params["LSEGMENT"]),
            ))
            start = end
    return tuple(sorted(rows))


def _topology(parsed: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    network = genkey_static._network_from_parsed(parsed, "candidate.genkey")
    return tuple(sorted((edge["source"], edge["target"], edge["label"]) for edge in network["edges"]))


def _junctions(parsed: dict[str, Any]) -> tuple[tuple[str, str, str, str], ...]:
    node_types = {item["tag"]: item["type"] for item in parsed.get("nodes", [])}
    flowpaths = {item["tag"] for item in parsed.get("flowpaths", [])}
    rows: list[tuple[str, str, str, str]] = []
    for connection in parsed.get("connections", []):
        terminals = connection.get("TERMINALS", [])
        flowpath = next((item for item in terminals if item.get("component") in flowpaths), None)
        junction = next((item for item in terminals if node_types.get(item.get("component")) == "JUNCTIONNODE"), None)
        if flowpath and junction:
            rows.append((junction["component"], flowpath["component"], flowpath["terminal"], junction["terminal"]))
    return tuple(sorted(rows))


def _fluid_labels(parsed: dict[str, Any]) -> tuple[str, ...]:
    labels: set[str] = set()
    for flowpath in parsed.get("flowpaths", []):
        for child in flowpath.get("children", []):
            if child.get("keyword") == "BRANCH":
                labels.add(str(child["params"]["FLUID"]))
    for node in parsed.get("nodes", []):
        for child in node.get("children", []):
            if child.get("keyword") == "PARAMETERS" and "FLUID" in child["params"]:
                labels.add(str(child["params"]["FLUID"]))
    return tuple(sorted(labels))


def _boundaries(parsed: dict[str, Any]) -> tuple[tuple[str, float, float], ...]:
    rows: list[tuple[str, float, float]] = []
    for node in parsed.get("nodes", []):
        for child in node.get("children", []):
            params = child.get("params", {})
            if child.get("keyword") == "PARAMETERS" and params.get("TYPE") == "PRESSURE":
                rows.append((str(params["LABEL"]), _number(params["PRESSURE"]), _number(params["TEMPERATURE"])))
    return tuple(sorted(rows))


def _roughness(parsed: dict[str, Any]) -> tuple[tuple[str, str, float], ...]:
    rows = [
        (flowpath["tag"], str(child["params"]["LABEL"]), _number(child["params"]["ROUGHNESS"]))
        for flowpath in parsed.get("flowpaths", [])
        for child in flowpath.get("children", [])
        if child.get("keyword") == "PIPE"
    ]
    return tuple(sorted(rows))


def _thermal(parsed: dict[str, Any]) -> tuple[Any, ...]:
    """Adiabatic flag, or the ambient heat-exchange rows and the single wall."""
    options = parsed["global_keywords"].get("OPTIONS", {})
    if str(options.get("TEMPERATURE", "")).strip().upper() == "ADIABATIC":
        return ("adiabatic",)
    rows: list[tuple[str, tuple[str, ...], float, float]] = []
    for flowpath in parsed.get("flowpaths", []):
        for child in flowpath.get("children", []):
            if child.get("keyword") != "HEATTRANSFER":
                continue
            params = child["params"]
            if params.get("HOUTEROPTION") != "HGIVEN":
                return ("unsupported_heat_transfer",)
            pipes = params["PIPE"] if isinstance(params["PIPE"], list) else [params["PIPE"]]
            rows.append((
                str(params["LABEL"]), tuple(str(item) for item in pipes),
                _number(params["TAMBIENT"]), _number(params["HAMBIENT"]),
            ))
    walls = tuple(
        (
            _values(wall["THICKNESS"]),
            tuple(wall["MATERIAL"] if isinstance(wall["MATERIAL"], list) else [wall["MATERIAL"]]),
        )
        for wall in parsed.get("walls", [])
    )
    materials = tuple(
        (_number(item["CONDUCTIVITY"]), _number(item["CAPACITY"]), _number(item["DENSITY"]))
        for item in parsed.get("materials", [])
    )
    return ("ambient_h_given", tuple(sorted(rows)), walls, materials)


def _verified(parsed: dict[str, Any]) -> ToolkitVerification:
    geometry = _geometry(parsed)
    globals_ = parsed["global_keywords"]
    outputs: set[str] = set()
    for flowpath in parsed.get("flowpaths", []):
        for child in flowpath.get("children", []):
            if child.get("keyword") == "OUTPUTDATA":
                value = child["params"].get("VARIABLE", [])
                outputs.update(str(item) for item in (value if isinstance(value, list) else [value]))
    return ToolkitVerification(
        True, True, True, (), _topology(parsed),
        sum(item[-2] for item in geometry), _junctions(parsed), geometry,
        str(globals_["FILES"]["PVTFILE"]), _seconds(globals_["INTEGRATION"]["ENDTIME"]), tuple(sorted(outputs)),
        _fluid_labels(parsed), _thermal(parsed), _boundaries(parsed), _roughness(parsed),
    )


def verify_with_toolkit(text: str) -> ToolkitVerification:
    with tempfile.TemporaryDirectory(prefix="olga-casespec-") as directory:
        candidate = Path(directory) / "candidate.genkey"
        candidate.write_text(text, encoding="utf-8", newline="\n")
        parser = genkey_static.run_tool("parser", [str(candidate), "--json", "--compact"])
        validator = genkey_static.run_tool("validator", [str(candidate)])
    try:
        parsed = json.loads(parser.stdout) if parser.exit_code == 0 else None
    except (json.JSONDecodeError, RecursionError):
        parsed = None
    parser_clean = isinstance(parsed, dict)
    validator_clean = validator.exit_code == 0
    if parser_clean and validator_clean:
        try:
            return _verified(parsed)
        except (KeyError, TypeError, ValueError, StopIteration) as error:
            return ToolkitVerification(False, False, True, (f"round-trip parse failed: {error}",))
    diagnostics = tuple(
        item for item in (parser.stderr.strip(), validator.stdout.strip(), validator.stderr.strip()) if item
    )[:8]
    return ToolkitVerification(False, parser_clean, validator_clean, diagnostics)
