from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Sequence

from .olga_runtime_paths import input_basename, path_key


MAX_EVIDENCE_BYTES = 256 * 1024
# Match solver-activity handling: tolerate only small cross-host/filesystem skew.
EVIDENCE_CLOCK_SKEW_TOLERANCE_SECONDS = 2.0
PATH_VERSION = re.compile(r"(?i)\bOLGA\s*[-_ ]?\s*(20\d{2})[._-](\d+)(?:[._-](\d+))?")
OUT_VERSION = re.compile(
    r"(?im)^\s*VERSION\s*:\s*OLGA\s+(20\d{2})\.(\d+)\.(\d+)(?:\.\d+)?\s*$"
)
OUT_INPUT = re.compile(r"(?im)^\s*INPUT\s+FILE\s*:\s*['\"]?([^'\"\r\n]+?)['\"]?\s*$")
NORMAL_STOP = re.compile(r"(?im)^.*\bNORMAL\s+STOP\s+IN\s+EXECUTION\b.*$")
RESULT_VERSION = re.compile(
    r"(?im)^\s*(['\"])OLGA\s+(20\d{2})\.(\d+)\.(\d+)(?:\.\d+)?\1\s*$"
)
RESULT_INPUT = re.compile(
    r"(?im)^\s*(['\"])INPUT\s+FILE\1\s+(['\"])([^'\"\r\n]+)\2\s*$"
)
RESULT_INPUT_MULTILINE = re.compile(
    r"(?im)^\s*(?:['\"])?INPUT\s+FILE(?:['\"])?\s*$\r?\n\s*(['\"])([^'\"\r\n]+)\1\s*$"
)


def version(groups: Sequence[str | None]) -> tuple[str, tuple[int, int, int]]:
    numbers = (int(groups[0] or 0), int(groups[1] or 0), int(groups[2] or 0))
    return ".".join(str(value) for value in numbers), numbers


def path_version(exe: str) -> tuple[str | None, tuple[int, int, int] | None]:
    path = Path(exe)
    for name in (path.name, *(parent.name for parent in path.parents)):
        match = PATH_VERSION.search(name)
        if match:
            return version(match.groups())
    return None, None


def read_bounded(path: Path) -> tuple[str, int]:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(0)
        if size <= MAX_EVIDENCE_BYTES:
            data = handle.read(MAX_EVIDENCE_BYTES)
            bytes_read = len(data)
        else:
            head_size = MAX_EVIDENCE_BYTES // 2
            tail_size = MAX_EVIDENCE_BYTES - head_size
            head = handle.read(head_size)
            if not head.endswith(b"\n"):
                last_newline = head.rfind(b"\n")
                head = head[: last_newline + 1] if last_newline >= 0 else b""

            # Spend one byte of the tail budget checking whether the retained
            # tail starts at a real line boundary. This keeps total I/O bounded
            # without inventing a separator between unrelated fragments.
            tail_payload_size = tail_size - 1
            tail_start = size - tail_payload_size
            handle.seek(tail_start - 1, os.SEEK_SET)
            tail_block = handle.read(tail_size)
            previous = tail_block[:1]
            tail = tail_block[1:]
            if previous != b"\n":
                first_newline = tail.find(b"\n")
                tail = tail[first_newline + 1 :] if first_newline >= 0 else b""
            data = head + tail
            bytes_read = head_size + len(tail_block)
    return data.decode("utf-8", errors="replace"), bytes_read


def evidence_from(
    path: Path, source_name: str, source_mtime_ns: int
) -> dict[str, Any] | None:
    try:
        text, bytes_read = read_bounded(path)
    except OSError:
        return None
    try:
        evidence_mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    if evidence_mtime_ns > time.time_ns() + int(
        EVIDENCE_CLOCK_SKEW_TOLERANCE_SECONDS * 1_000_000_000
    ):
        return None
    suffix = path.suffix.lower()
    if suffix == ".out":
        version_match = OUT_VERSION.search(text)
        input_match = OUT_INPUT.search(text)
        if not version_match or not input_match or not NORMAL_STOP.search(text):
            return None
        source_type = "solver-out"
        normal_stop = True
        input_group = input_match.group(1)
        version_groups = version_match.groups()
    elif suffix in {".tpl", ".ppl"}:
        version_match = RESULT_VERSION.search(text)
        input_match = RESULT_INPUT.search(text) or RESULT_INPUT_MULTILINE.search(text)
        if not version_match or not input_match:
            return None
        source_type = "solver-tpl" if suffix == ".tpl" else "solver-ppl"
        normal_stop = None
        input_group = (
            input_match.group(3)
            if input_match.re is RESULT_INPUT
            else input_match.group(2)
        )
        version_groups = version_match.groups()[1:]
    else:
        return None
    if input_basename(input_group).casefold() != source_name.casefold():
        return None
    release, _ = version(version_groups)
    evidence = {
        "source_type": source_type,
        "path": str(path),
        "version": release,
        "strength": "stale" if evidence_mtime_ns < source_mtime_ns else "strong",
        "input_file": input_group.strip(),
        "bytes_read": bytes_read,
    }
    if normal_stop is not None:
        evidence["normal_stop"] = normal_stop
    return evidence


def case_evidence(source: str | Path | None) -> tuple[str | None, list[dict[str, Any]]]:
    if source is None:
        return None, []
    case = Path(source).expanduser()
    case_value = str(case)
    if case.suffix.lower() != ".genkey" or not case.is_file():
        return case_value, []
    try:
        source_mtime_ns = case.stat().st_mtime_ns
    except OSError:
        return case_value, []
    directories = (case.parent, case.parent / "results")
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for suffix in (".out", ".tpl", ".ppl"):
        for directory in directories:
            path = directory / f"{case.stem}{suffix}"
            key = path_key(str(path))
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            item = evidence_from(path, case.name, source_mtime_ns)
            if item is not None:
                evidence.append(item)
    return case_value, evidence
