"""Build the shipped OLGA glossary from the named source files only."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Folder holding genkey-keywords.md and validation-rules.md (not part of this repository).
OWNER = Path(os.environ.get("OLGA_GLOSSARY_SOURCES", "glossary-sources"))
OUT = REPO / "src" / "olga_companion" / "resources" / "olga_glossary.json"
HEADING = re.compile(r"^### ([A-Z][A-Z0-9_]+)\s*$")
PARAM = re.compile(r"`([A-Z][A-Z0-9_]+)`")
TOKEN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
DOCSTRING = re.compile(r'"""(.*?)"""', re.DOTALL)
DOC_TERM = re.compile(r"\b(?:Add|Set)(?: a)? ([A-Z][A-Z0-9_]+) keyword\b")
CATALOG = re.compile(r"\b([A-Z][A-Z0-9_]{1,8})\b.*'\(([^)]+)\)'\s+'([^']+)'")
SKIP = frozenset({"ERROR", "WARNING", "INFO", "TAG", "TYPE", "ON", "OFF", "OLGA"})


def build_entries() -> list[dict]:
    entries: dict[str, dict] = {}
    keywords = _read(OWNER / "genkey-keywords.md")
    rules = _read(OWNER / "validation-rules.md")
    validator = _read(REPO / "resources/olga-toolkit/scripts/genkey_validator.py")
    parser = _read(REPO / "resources/olga-toolkit/scripts/result_parser.py")
    builder = _read(REPO / "resources/olga-toolkit/scripts/genkey_builder.py")
    variables = _read(REPO / "frontend/src/resultPresentation.ts")
    _keywords_and_parameters(entries, keywords, "genkey-keywords.md")
    known = set(entries)
    _validation_terms(entries, rules, validator, known)
    _docstring_terms(entries, parser, "result_parser.py")
    _docstring_terms(entries, builder, "genkey_builder.py")
    _docstring_terms(entries, validator, "genkey_validator.py")
    _catalog_variables(entries, parser)
    _korean_variables(entries, variables)
    _vendor_definitions(entries, REPO / "resources/olga-vendor/keyinfo-fractions.json")
    return [entries[term] for term in sorted(entries)]


def write_glossary() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(build_entries(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _add(entries: dict[str, dict], term: str, kind: str, meaning: str, source_file: str, line: int, unit: str | None) -> None:
    term = term.strip().upper()
    meaning = " ".join(meaning.replace("`", "").split())
    if not term or not meaning or term in entries or term in SKIP:
        return
    item = {
        "kind": kind,
        "meaning": meaning,
        "source": {"file": source_file, "line": line},
        "term": term,
    }
    cleaned_unit = " ".join(unit.split()) if unit else ""
    if cleaned_unit and cleaned_unit not in {"—", "-"}:
        item["unit"] = cleaned_unit
    entries[term] = item


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _keywords_and_parameters(entries: dict[str, dict], lines: list[str], source_file: str) -> None:
    headers: list[str] = []
    for index, line in enumerate(lines, start=1):
        heading = HEADING.match(line)
        if heading:
            meaning = _next_prose(lines, index)
            if meaning:
                _add(entries, heading.group(1), "keyword", meaning[1], source_file, meaning[0], None)
            continue
        if line.startswith("| Parameter"):
            headers = [cell.strip().lower() for cell in _cells(line)]
            continue
        if not line.startswith("| `") or not headers:
            continue
        cells = _cells(line)
        match = PARAM.search(cells[0]) if cells else None
        if not match or len(cells) != len(headers):
            continue
        fields = dict(zip(headers, cells))
        _add(
            entries,
            match.group(1),
            "parameter",
            fields.get("description", ""),
            source_file,
            index,
            fields.get("unit") or None,
        )


def _next_prose(lines: list[str], heading_index: int) -> tuple[int, str] | None:
    for offset, line in enumerate(lines[heading_index:], start=heading_index + 1):
        text = line.strip()
        if not text or text == "---":
            continue
        if text.startswith("|") or text.startswith("#") or text.startswith("```"):
            return None
        return offset, text.split(". ")[0].rstrip(".") + "."
    return None


def _validation_terms(entries: dict[str, dict], rules: list[str], validator: list[str], known: set[str]) -> None:
    validator_text = "\n".join(validator)
    for index, line in enumerate(rules, start=1):
        if not line.startswith("| ") or line.startswith("| ID") or line.startswith("|----"):
            continue
        cells = _cells(line)
        if len(cells) < 4:
            continue
        meaning = cells[-1]
        for token in TOKEN.findall(f"{cells[2]} {cells[3]}"):
            if token in known or token in entries or token not in validator_text:
                continue
            _add(entries, token, "keyword", meaning, "validation-rules.md", index, None)


def _docstring_terms(entries: dict[str, dict], lines: list[str], source_file: str) -> None:
    text = "\n".join(lines)
    for match in DOCSTRING.finditer(text):
        body = match.group(1)
        start = text[: match.start()].count("\n") + 1
        for offset, line in enumerate(body.splitlines()):
            named = DOC_TERM.search(line)
            if not named:
                continue
            sentence = " ".join(line.strip().split()).strip('"')
            _add(entries, named.group(1), "keyword", sentence, source_file, start + offset, None)


def _catalog_variables(entries: dict[str, dict], lines: list[str]) -> None:
    for index, line in enumerate(lines, start=1):
        match = CATALOG.search(line)
        if not match:
            continue
        _add(
            entries,
            match.group(1),
            "output_variable",
            match.group(3),
            "result_parser.py",
            index,
            match.group(2),
        )


def _korean_variables(entries: dict[str, dict], lines: list[str]) -> None:
    row = re.compile(r"^\s{2}([A-Z][A-Z0-9_]*): '([^']+)',?\s*$")
    in_map = False
    for index, line in enumerate(lines, start=1):
        if "PLAIN_VARIABLE_NAMES" in line:
            in_map = True
            continue
        if not in_map:
            continue
        if line.strip() == "};":
            break
        match = row.match(line)
        if not match:
            continue
        term = match.group(1)
        entries[term] = {
            "kind": "output_variable",
            "meaning": match.group(2),
            "source": {"file": "resultPresentation.ts", "line": index},
            "term": term,
        }


def _vendor_definitions(entries: dict[str, dict], path: Path) -> None:
    """The OLGA install's own key definitions win over the owner notes they replace."""
    for row in json.loads(path.read_text(encoding="utf-8")):
        entries[row["term"]] = {
            "kind": "parameter",
            "meaning": row["meaning"],
            "source": {"file": row["file"], "line": row["line"]},
            "term": row["term"],
            "unit": row["unit"],
        }


if __name__ == "__main__":
    write_glossary()
