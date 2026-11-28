"""set_pipe_length on an owner GENKEY: rewrite only the numbers that make up one pipe's length.

The pipe's LSEGMENT list scales with the new length (and LENGTH, when it has one). A pipe drawn
by end coordinates is stretched along its own direction, and every later pipe of the same
flowpath moves by the same offset, so the rest of the line keeps its shape. Units stay as written.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .case_transaction_models import SemanticDiff, SetPipeLength

_TO_M = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "in": 0.0254}
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_UNIT = r"(?:\s*(?P<unit>[A-Za-z]+)\b(?!\s*=))?"
_SCALAR = re.compile(rf"(?<![A-Za-z0-9_])(?P<key>[A-Z]+)\s*=\s*(?P<number>{_NUMBER}){_UNIT}", re.IGNORECASE)
_LIST = re.compile(rf"(?<![A-Za-z0-9_])LSEGMENT\s*=\s*\((?P<numbers>[^)]*)\){_UNIT}", re.IGNORECASE)
_LABEL = re.compile(r"(?<![A-Za-z0-9_])(?P<key>LABEL|TAG)\s*=\s*\"?(?P<value>[^\",\s\\]+)\"?", re.IGNORECASE)


class OwnerEditError(Exception):
    """The edit cannot be made on this GENKEY; `code` is the transaction failure code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _Statement:
    keyword: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Value:
    number: float
    unit: str
    start: int
    end: int

    @property
    def metres(self) -> float:
        return self.number * _TO_M[self.unit]


def _statements(text: str) -> list[_Statement]:
    statements: list[_Statement] = []
    lines = text.splitlines(keepends=True)
    offset = index = 0
    while index < len(lines):
        start, line = offset, lines[index]
        offset += len(line)
        index += 1
        while line.rstrip("\r\n").endswith("\\") and index < len(lines):
            line = lines[index]
            offset += len(line)
            index += 1
        stripped = text[start:offset].strip()
        if stripped and not stripped.startswith("!"):
            statements.append(_Statement(stripped.split(None, 1)[0].rstrip(",").upper(), start, offset))
    return statements


def _unit(raw: str | None) -> str:
    unit = (raw or "m").lower()
    if unit not in _TO_M:
        raise OwnerEditError("unit_unchanged", f"Length unit {raw!r} is not one this edit converts.")
    return unit


def _scalars(text: str, statement: _Statement) -> dict[str, _Value]:
    found: dict[str, _Value] = {}
    for match in _SCALAR.finditer(text, statement.start, statement.end):
        key = match.group("key").upper()
        if key in {"LENGTH", "ELEVATION", "XSTART", "YSTART", "ZSTART", "XEND", "YEND", "ZEND"}:
            found[key] = _Value(float(match.group("number")), _unit(match.group("unit")),
                                match.start("number"), match.end("number"))
    return found


def _point(values: dict[str, _Value], suffix: str) -> tuple[float, float, float] | None:
    if f"X{suffix}" not in values or f"Y{suffix}" not in values:
        return None
    z = values.get(f"Z{suffix}")
    return (values[f"X{suffix}"].metres, values[f"Y{suffix}"].metres, z.metres if z else 0.0)


def _render(value: float) -> str:
    text = f"{value:.10g}"
    return "0" if text in {"-0", "+0"} else text


def _label_of(text: str, statement: _Statement, key: str) -> str | None:
    for match in _LABEL.finditer(text, statement.start, statement.end):
        if match.group("key").upper() == key:
            return match.group("value")
    return None


def _flowpath(text: str, statements: list[_Statement], wanted: str) -> list[_Statement]:
    """The statements of the one FLOWPATH whose TAG or PARAMETERS LABEL is `wanted`."""
    blocks: list[list[_Statement]] = []
    current: list[_Statement] | None = None
    for statement in statements:
        if statement.keyword == "NETWORKCOMPONENT":
            body = text[statement.start:statement.end].upper().replace(" ", "")
            current = [statement] if "TYPE=FLOWPATH" in body else None
            if current is not None:
                blocks.append(current)
        elif statement.keyword == "ENDNETWORKCOMPONENT":
            current = None
        elif current is not None:
            current.append(statement)
    target = wanted.casefold()
    matches = [
        block for block in blocks
        if (_label_of(text, block[0], "TAG") or "").casefold() == target
        or any(s.keyword == "PARAMETERS" and (_label_of(text, s, "LABEL") or "").casefold() == target for s in block)
    ]
    if len(matches) != 1:
        raise OwnerEditError("unknown_target", f"Edit target does not exist: flowpath {wanted}")
    return matches[0]


def apply_owner_pipe_length(text: str, operation: SetPipeLength) -> tuple[str, SemanticDiff]:
    block = _flowpath(text, _statements(text), operation.flowpath)
    pipes = [s for s in block if s.keyword == "PIPE"]
    chosen = [s for s in pipes if (_label_of(text, s, "LABEL") or "").casefold() == operation.pipe.casefold()]
    if len(chosen) != 1:
        raise OwnerEditError("unknown_target", f"Edit target does not exist: {operation.flowpath}/{operation.pipe}")
    pipe = chosen[0]

    point: tuple[float, float, float] | None = None
    start: tuple[float, float, float] | None = None
    for statement in block:
        if statement.keyword == "GEOMETRY":
            point = _point(_scalars(text, statement), "START") or (0.0, 0.0, 0.0)
        elif statement.keyword == "PIPE":
            if statement is pipe:
                start = point
                break
            point = _point(_scalars(text, statement), "END")

    values = _scalars(text, pipe)
    segments = _LIST.search(text, pipe.start, pipe.end)
    end = _point(values, "END")
    if segments is None:
        raise OwnerEditError("unsupported_operation", f"{operation.pipe} has no LSEGMENT list to scale.")
    seg_unit = _unit(segments.group("unit"))
    seg_numbers = [float(n) for n in segments.group("numbers").replace(",", " ").split()]
    if "LENGTH" in values:
        before = values["LENGTH"].metres
    elif end is not None:
        if start is None:
            raise OwnerEditError("unsupported_operation", f"The start point of {operation.pipe} is not known.")
        before = math.dist(start, end)
    else:
        before = math.fsum(seg_numbers) * _TO_M[seg_unit]
    if before <= 0 or not seg_numbers:
        raise OwnerEditError("unsupported_operation", f"{operation.pipe} has no length to scale.")
    ratio = operation.length_m / before
    elevation = values.get("ELEVATION")
    if elevation is not None and abs(elevation.metres) > operation.length_m + 1e-9:
        raise OwnerEditError(
            "unsupported_operation",
            f"{operation.pipe} rises or falls {abs(elevation.metres):g} m, more than {operation.length_m:g} m.",
        )

    edits: list[tuple[int, int, str]] = []
    scaled = [_render(n * ratio) for n in seg_numbers]
    total = math.fsum(seg_numbers) * ratio
    scaled[-1] = _render(total - math.fsum(float(n) for n in scaled[:-1]))
    edits.append((segments.start("numbers"), segments.end("numbers"), ", ".join(scaled)))
    if "LENGTH" in values:
        length = values["LENGTH"]
        edits.append((length.start, length.end, _render(operation.length_m / _TO_M[length.unit])))

    later = [s for s in pipes if s.start > pipe.start]
    if end is not None and start is not None:
        moved = tuple(a + (b - a) * ratio for a, b in zip(start, end))
        shift = tuple(m - e for m, e in zip(moved, end))
        for statement in [pipe, *later]:
            coords = _scalars(text, statement)
            for axis, delta in zip("XYZ", shift):
                value = coords.get(f"{axis}END")
                if value is not None and delta:
                    edits.append((value.start, value.end, _render(value.number + delta / _TO_M[value.unit])))
                elif value is None and delta and statement is pipe:
                    raise OwnerEditError("unsupported_operation", f"{operation.pipe} has no {axis}END to move.")
    elif any(_point(_scalars(text, s), "END") is not None for s in later):
        raise OwnerEditError(
            "unsupported_operation", f"Later pipes are drawn by coordinates but {operation.pipe} is not."
        )

    revised = text
    for begin, finish, replacement in sorted(edits, reverse=True):
        revised = revised[:begin] + replacement + revised[finish:]
    return revised, SemanticDiff(
        f"flowpaths.{operation.flowpath}.pipes.{operation.pipe}.length_m", before, operation.length_m
    )
