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


def discover_sweep_parameters(path: Path) -> tuple[SweepParameter, ...]:
    """Return unambiguous sweepable parameter paths found in a GENKEY case."""
    source = require_genkey_path(str(path))
    candidates = tuple(_parameter_paths(_logical_records(source)))
    counts = Counter(parameter.path for parameter in candidates)
    return tuple(parameter for parameter in candidates if counts[parameter.path] == 1)


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
        for key_match in _ASSIGNMENT_PATTERN.finditer(match.group(2)):
            key = key_match.group(1).upper()
            yield SweepParameter(
                path=f"{keyword}.{key}",
                keyword=keyword,
                key=key,
            )
