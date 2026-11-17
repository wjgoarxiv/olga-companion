from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import TypedDict

from .fluids import PVTFILE_PATTERN


class CompanionEvidence(TypedDict):
    pvt_files: list[str]
    pvt_missing: list[str]
    restart_files: list[str]
    restart_missing: list[str]


class CompanionManifestEntry(TypedDict):
    kind: str
    reference: str
    resolved_path: str | None
    sha256: str | None


RESTART_LINE_PATTERN = re.compile(r"^[ \t]*RESTART\b[^\r\n]*", re.IGNORECASE | re.MULTILINE)
READFILE_PATTERN = re.compile(r"\bREADFILE\s*=\s*(ON|OFF)\b", re.IGNORECASE)
RESTART_FILE_PATTERN = re.compile(
    r"\bFILE\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^,\s]+))",
    re.IGNORECASE,
)


def companion_references(text: str) -> list[tuple[str, str | None]]:
    references: list[tuple[str, str | None]] = []
    for match in PVTFILE_PATTERN.finditer(text):
        references.append(("pvt", match.group(1) or match.group(2)))
    for line_match in RESTART_LINE_PATTERN.finditer(text):
        line = line_match.group(0)
        readfile = READFILE_PATTERN.search(line)
        if readfile is None or readfile.group(1).upper() != "ON":
            continue
        file_match = RESTART_FILE_PATTERN.search(line)
        raw = None if file_match is None else next(value for value in file_match.groups() if value is not None)
        references.append(("restart", raw))
    return references


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def companion_manifest(source: Path) -> list[CompanionManifestEntry]:
    return effective_companion_manifest(source)


def effective_companion_manifest(
    source: Path,
    fallback_source: Path | None = None,
) -> list[CompanionManifestEntry]:
    text = source.read_text(encoding="utf-8", errors="replace")
    manifest: list[CompanionManifestEntry] = []
    for kind, raw in companion_references(text):
        if raw is None:
            manifest.append({"kind": kind, "reference": "<FILE not set>", "resolved_path": None, "sha256": None})
            continue
        ref = Path(raw)
        primary = ref if ref.is_absolute() else source.parent / ref
        if primary.is_file() or fallback_source is None:
            resolved = primary.resolve()
        else:
            fallback = ref if ref.is_absolute() else fallback_source.parent / ref
            resolved = fallback.resolve()
        manifest.append(
            {
                "kind": kind,
                "reference": raw,
                "resolved_path": str(resolved),
                "sha256": _file_sha256(resolved),
            }
        )
    return sorted(manifest, key=lambda item: (item["kind"], item["reference"], item["resolved_path"] or ""))


def _stage_destination(entry: CompanionManifestEntry, run_dir: Path) -> tuple[Path | None, str]:
    raw = entry["reference"]
    resolved_path = entry["resolved_path"]
    if resolved_path is None:
        return None, raw
    ref = Path(raw)
    run_root = run_dir.resolve()
    candidate = (run_dir / ref).resolve()
    contained = not ref.is_absolute() and (candidate == run_root or run_root in candidate.parents)
    if contained:
        destination = run_dir / ref
        rewritten = raw
    else:
        destination = run_dir / Path(resolved_path).name
        rewritten = f"./{Path(resolved_path).name}"
    return destination, rewritten


def expected_staged_source_sha256(
    source: Path,
    manifest: list[CompanionManifestEntry],
    run_dir: Path,
) -> str:
    text = source.read_text(encoding="utf-8", errors="replace")
    updated = text
    for entry in manifest:
        if entry["sha256"] is None:
            continue
        _, rewritten = _stage_destination(entry, run_dir)
        raw = entry["reference"]
        if rewritten != raw:
            updated = updated.replace(raw, rewritten)
    if updated == text:
        digest = _file_sha256(source)
        if digest is None:
            raise OSError(f"Could not hash staged source candidate: {source}")
        return digest
    return hashlib.sha256(updated.encode("utf-8")).hexdigest()


def staged_companions_match(
    manifest: list[CompanionManifestEntry],
    run_dir: Path,
) -> bool:
    for entry in manifest:
        destination, _ = _stage_destination(entry, run_dir)
        actual = None if destination is None else _file_sha256(destination)
        if actual != entry["sha256"]:
            return False
    return True


def _stage_reference(
    source: Path,
    run_dir: Path,
    raw: str,
    fallback_source: Path | None = None,
) -> tuple[Path | None, str]:
    ref = Path(raw)
    primary = ref if ref.is_absolute() else source.parent / ref
    if primary.is_file():
        resolved = primary
    elif fallback_source is not None:
        fallback = ref if ref.is_absolute() else fallback_source.parent / ref
        resolved = fallback
    else:
        resolved = primary
    if not resolved.is_file():
        return None, raw

    entry: CompanionManifestEntry = {
        "kind": "",
        "reference": raw,
        "resolved_path": str(resolved.resolve()),
        "sha256": None,
    }
    destination, rewritten = _stage_destination(entry, run_dir)
    if destination is None:
        return None, raw
    destination.parent.mkdir(parents=True, exist_ok=True)
    if resolved.resolve() != destination.resolve():
        shutil.copy2(resolved, destination)
    return destination, rewritten


def stage_companions(
    source: Path,
    working_copy: Path,
    run_dir: Path,
    fallback_source: Path | None = None,
) -> CompanionEvidence:
    text = working_copy.read_text(errors="replace")
    evidence: CompanionEvidence = {
        "pvt_files": [],
        "pvt_missing": [],
        "restart_files": [],
        "restart_missing": [],
    }

    for kind, raw in companion_references(text):
        if raw is None:
            evidence["restart_missing"].append("<FILE not set>")
            continue
        destination, rewritten = _stage_reference(source, run_dir, raw, fallback_source)
        if destination is None:
            evidence[f"{kind}_missing"].append(raw)
            continue
        evidence[f"{kind}_files"].append(raw)
        if rewritten != raw:
            text = text.replace(raw, rewritten)

    if text != working_copy.read_text(errors="replace"):
        working_copy.write_text(text)
    return evidence
