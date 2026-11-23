from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .genkey_static import require_genkey_path

_RECORD_PATTERN: Final = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\b(.*)$")
_ASSIGNMENT_PATTERN: Final = re.compile(r"(?:^|,)\s*([A-Za-z][A-Za-z0-9_]*)\s*=")


@dataclass(frozen=True, slots=True)
class SweepParameter:
    path: str
    keyword: str
    key: str


def sweep_parameter_catalog(path: Path) -> tuple[tuple[SweepParameter, ...], tuple[str, ...]]:
    """One read of the case: the sweepable paths, and the paths that appear more than once
    (a sweep cannot tell which of those to change)."""
    source = require_genkey_path(str(path))
    candidates = tuple(_parameter_paths(_logical_records(source)))
    counts = Counter(parameter.path for parameter in candidates)
    unique = tuple(parameter for parameter in candidates if counts[parameter.path] == 1)
    return unique, tuple(sorted(name for name, count in counts.items() if count > 1))


def discover_sweep_parameters(path: Path) -> tuple[SweepParameter, ...]:
    """Return unambiguous sweepable parameter paths found in a GENKEY case."""
    return sweep_parameter_catalog(path)[0]


def ambiguous_sweep_parameters(path: Path) -> tuple[str, ...]:
    """Paths that appear more than once, so a sweep cannot tell which one to change."""
    return sweep_parameter_catalog(path)[1]


def _logical_records(path: Path) -> Iterator[str]:
    pending = ""
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for raw_line in source:
            stripped = raw_line.strip()
            if not pending and (not stripped or stripped.startswith("!")):
                continue
            continues = stripped.endswith("\\")
            fragment = stripped[:-1].rstrip() if continues else stripped
            pending = f"{pending} {fragment}".strip()
            if not continues:
                if pending:
                    yield pending
                pending = ""
    if pending:
        yield pending


def _parameter_paths(records: Iterator[str]) -> Iterator[SweepParameter]:
    for record in records:
        match = _RECORD_PATTERN.match(record)
        if match is None:
            continue
        keyword = match.group(1).upper()
        body = match.group(2)
        for key_match in _ASSIGNMENT_PATTERN.finditer(body):
            # A bracketed list value such as THICKNESS=(0.0127) m is not offered: the sweep writer
            # would replace it with a bare number and drop the list and its unit.
            if body[key_match.end():].lstrip().startswith("("):
                continue
            key = key_match.group(1).upper()
            yield SweepParameter(
                path=f"{keyword}.{key}",
                keyword=keyword,
                key=key,
            )
