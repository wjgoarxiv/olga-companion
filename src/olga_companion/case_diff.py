"""Keyword-level differences between two .genkey files, read-only.

Each record is identified by its network component (the TAG of the NETWORKCOMPONENT it sits
in), its keyword and its LABEL; a record without a LABEL is identified by its order among
records of the same keyword in that component, lined up by content so a deleted record does
not shift the ones after it. Values are compared as OLGA reads them, so
comments, line breaks, spacing inside lists and the order of keys never show as changes.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from .case_lint import _records

_MAX_ROWS = 400


def _shown(entry: tuple[str, list[str] | None, str | None]) -> str:
    kind, items, text = entry
    if kind == "list":
        inner = ", ".join(items or [])
        return f"({inner}) {text}".strip() if text else f"({inner})"
    if kind == "text":
        return f'"{text or ""}"'
    return text or ""


Values = dict[str, str]
Identity = tuple[str, str, str]


def _parsed(text: str) -> tuple[dict[Identity, Values], dict[tuple[str, str], list[Values]]]:
    """Labelled records by (component, keyword, LABEL); unlabelled ones in file order per
    (component, keyword)."""
    labelled: dict[Identity, Values] = {}
    unlabelled: dict[tuple[str, str], list[Values]] = {}
    component = ""
    for keyword, values in _records(text):
        if keyword == "NETWORKCOMPONENT":
            tag = values.get("TAG")
            component = (tag[2] if tag and tag[2] else "?").upper()
        elif keyword == "ENDNETWORKCOMPONENT":
            component = ""
            continue
        shown = {key: _shown(entry) for key, entry in values.items()}
        label = values.get("LABEL")
        if label and label[2]:
            labelled[(component, keyword, label[2])] = shown
        else:
            unlabelled.setdefault((component, keyword), []).append(shown)
    return labelled, unlabelled


def _aligned(old: list[Values], new: list[Values]) -> list[tuple[int | None, int | None]]:
    """Pairs of positions (before, after) for records without a LABEL. Identical records are
    lined up first, so a deleted or inserted record does not shift the ones after it; inside a
    run that differs, records pair in order and the rest are removed or added."""
    key = lambda values: tuple(sorted(values.items()))  # noqa: E731
    matcher = difflib.SequenceMatcher(a=[key(v) for v in old], b=[key(v) for v in new], autojunk=False)
    pairs: list[tuple[int | None, int | None]] = []
    for _tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for offset in range(max(i2 - i1, j2 - j1)):
            i = i1 + offset if i1 + offset < i2 else None
            j = j1 + offset if j1 + offset < j2 else None
            pairs.append((i, j))
    return pairs


def _row(identity: Identity, **fields: Any) -> dict[str, Any]:
    component, keyword, name = identity
    return {"component": component or None, "keyword": keyword, "label": name, **fields}


def _compare(identity: Identity, old: Values, new: Values, changed: list[dict[str, Any]]) -> None:
    for key in sorted(old.keys() | new.keys()):
        if old.get(key) != new.get(key):
            changed.append(_row(identity, key=key, before=old.get(key), after=new.get(key)))


def diff_texts(before: str, after: str) -> dict[str, Any]:
    a, a_free = _parsed(before)
    b, b_free = _parsed(after)
    changed: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    for identity in a:
        if identity in b:
            _compare(identity, a[identity], b[identity], changed)
        else:
            removed.append(_row(identity))
    added.extend(_row(identity) for identity in b if identity not in a)
    # A record without a LABEL is named by its place among its kind: #n in the case it is in.
    for group in list(a_free) + [group for group in b_free if group not in a_free]:
        old, new = a_free.get(group, []), b_free.get(group, [])
        for i, j in _aligned(old, new):
            if i is not None and j is not None:
                _compare((*group, f"#{i + 1}"), old[i], new[j], changed)
            elif i is not None:
                removed.append(_row((*group, f"#{i + 1}")))
            elif j is not None:
                added.append(_row((*group, f"#{j + 1}")))
    total = len(changed) + len(removed) + len(added)
    return {
        "same": total == 0,
        "changed": changed[:_MAX_ROWS],
        "removed": removed[:_MAX_ROWS],
        "added": added[:_MAX_ROWS],
        "truncated": any(len(rows) > _MAX_ROWS for rows in (changed, removed, added)),
    }


def diff_cases(before: Path, after: Path) -> dict[str, Any]:
    read = lambda path: path.read_text(encoding="utf-8", errors="replace")  # noqa: E731
    return diff_texts(read(before), read(after))
