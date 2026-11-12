from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .config import exports_root, toolkit_dir
from .result_export_paths import create_export_dir
from .sidecar_save_as_fsync import fsync_directory
from .fluids import require_fluid_path
from .genkey_static import OlgaInputError, file_sha256, require_genkey_path, run_tool
from .results import NAME_TOKEN

REPORT_SCRIPTS = {
    "report_generator": "report_generator.py",
    "figure_generator": "figure_generator.py",
    "result_comparator": "result_comparator.py",
}

FIGURE_KINDS = {
    "hol-profile": {".ppl"},
    "liqc-timeseries": {".tpl"},
}

REPORT_TIMEOUT_S = 180

# report_generator embeds tool failures in the Markdown body while still
# exiting 0, so the written report is scanned for these markers.
FAILURE_MARKERS = ("Traceback (most recent call last)", "ERROR:", "Error:")


def embedded_failure_markers(text: str) -> list[str]:
    return [marker for marker in FAILURE_MARKERS if marker in text]


def reports_toolkit_status() -> dict[str, Any]:
    root = toolkit_dir()
    scripts = {name: (root / "scripts" / script).exists() for name, script in REPORT_SCRIPTS.items()}
    return {
        "toolkit_dir": str(root),
        "available": root.exists() and all(scripts.values()),
        "scripts": scripts,
    }


def _token(value: str, what: str) -> str:
    value = str(value).strip()
    if not value or not NAME_TOKEN.fullmatch(value) or value.startswith("-"):
        raise OlgaInputError(f"Invalid {what}: {value!r}")
    return value


def _report_dir() -> Path:
    path = exports_root() / "reports" / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=False)
    return path


def _source_evidence(label: str, path: Path, before: str) -> dict[str, Any]:
    after = file_sha256(path)
    return {
        "role": label,
        "file": str(path),
        "sha256": before,
        "mutated": before != after,
    }


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _single_line(value: object) -> str:
    return " ".join(str(value).replace("`", " ").split())


def _plain(value: Any) -> str:
    if isinstance(value, str):
        return value.replace("\r", " ").replace("\n", " ")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _input_required(verdict: dict[str, Any]) -> bool:
    return str(verdict.get("status", "")).strip().lower() == "input_required"


def _citation_sources(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    nested = verdict.get("citations")
    if isinstance(nested, dict):
        return [nested]
    if isinstance(nested, list):
        return [item for item in nested if isinstance(item, dict)]
    return [verdict]


_CITATION_KEYS = (
    "source_file",
    "source_sha256",
    "source_mutated",
    "variables",
    "timestep",
    "mapping",
    "formula",
    "threshold",
    "command",
)


def _verdict_section(verdicts: list[dict[str, Any]]) -> str:
    lines = ["## 판정 결과", ""]
    for verdict in verdicts:
        lines.append(f"### {_single_line(verdict.get('criterion') or 'criterion')}")
        lines.append("")
        if _input_required(verdict):
            lines.append("상태: 입력 필요")
            missing = verdict.get("missing")
            if isinstance(missing, list) and missing:
                lines.append("필요 입력: " + ", ".join(_plain(item) for item in missing))
            lines.append("")
            continue
        label = verdict.get("verdict")
        if label is None and verdict.get("status") not in (None, ""):
            label = verdict.get("status")
        if label is not None:
            lines.append(f"판정: {_single_line(label)}")
        lines.append("")
        lines.append("인용:")
        for source in _citation_sources(verdict):
            for key in _CITATION_KEYS:
                if source.get(key) is None:
                    continue
                lines.append(f"- {key}: {_plain(source[key])}")
        values = verdict.get("values", verdict.get("measured"))
        if values is not None:
            lines.append(f"- values: {_plain(values)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _figure_section(figures: list[str]) -> str:
    lines = ["## 그림", ""]
    for figure in figures:
        path = str(figure).replace("\\", "/").replace("\r", "").replace("\n", "")
        lines.append(f"![]({path})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _cited_files(verdicts: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for verdict in verdicts:
        if _input_required(verdict):
            continue
        criterion = _single_line(verdict.get("criterion") or "verdict")
        for source in _citation_sources(verdict):
            sha = source.get("source_sha256")
            if not isinstance(sha, str) or not sha:
                continue
            path = source.get("source_file")
            rows.append(
                (
                    criterion,
                    _single_line("" if path is None else path),
                    _single_line(sha),
                )
            )
    return rows


def _sources_lines(
    sources: list[dict[str, Any]], verdicts: list[dict[str, Any]]
) -> list[str]:
    lines = ["", "## Sources", ""]
    lines.extend(
        f"- {entry['role']}: `{entry['file']}` (sha256 `{entry['sha256']}`)"
        for entry in sources
    )
    lines.extend(
        f"- citation {_single_line(criterion)}: `{_single_line(path)}` (sha256 `{_single_line(sha)}`)"
        for criterion, path, sha in _cited_files(verdicts)
    )
    return lines


def _checked_verdicts(verdicts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items = list(verdicts or [])
    if any(not isinstance(item, dict) for item in items):
        raise OlgaInputError("Each verdict must be an object.")
    return items


def _checked_figures(figures: list[str] | None) -> list[str]:
    items = list(figures or [])
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise OlgaInputError("Each figure must be a path.")
    return items


def _findings_filename(case: Path) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in case.stem)
    cleaned = cleaned.strip("-") or "case"
    return f"findings-{cleaned}.md"


def findings_report(
    case_file: str,
    results_file: str,
    verdicts: list[dict[str, Any]] | None = None,
    figures: list[str] | None = None,
    variables: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, str]:
    """Build a findings report in memory. Saving stays on the native save-as path."""
    case = require_genkey_path(case_file)
    results = require_fluid_path(results_file, {".tpl", ".ppl"})
    verdict_list = _checked_verdicts(verdicts)
    figure_list = _checked_figures(figures)
    variable_list = [name for name in (variables or []) if isinstance(name, str) and name.strip()]
    sources = [
        _source_evidence("case", case, file_sha256(case)),
        _source_evidence("results", results, file_sha256(results)),
    ]
    verdict_block = (
        _verdict_section(verdict_list).rstrip()
        if verdict_list
        else "## 판정 결과\n\n판정: 입력 필요(사용자가 생략)"
    )
    parts = [
        "# 판정 보고서",
        "",
        f"사례: `{case.name}`",
        f"결과: `{results.name}`",
    ]
    if run_id is not None:
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise OlgaInputError("run_id must be letters, digits, '_' or '-'.")
        parts.append(f"실행: `{run_id}`")
    parts.extend(["", verdict_block])
    if variable_list:
        parts.extend(["", "## 변수", ""])
        parts.extend(f"- {_single_line(name)}" for name in variable_list)
    if figure_list:
        parts.extend(["", _figure_section(figure_list).rstrip()])
    markdown = "\n".join(parts).rstrip() + "\n".join(_sources_lines(sources, verdict_list)) + "\n"
    return {"markdown": markdown, "filename": _findings_filename(case)}


def stage_findings_markdown(markdown: str, filename: str) -> str:
    """Write a findings report under the export root so Save As can copy it."""
    name = Path(filename).name
    if name != filename or name.startswith(".") or Path(name).suffix.casefold() != ".md":
        raise OlgaInputError("Findings filename must be a Markdown basename.")
    directory = create_export_dir(exports_root)
    path = directory / name
    with path.open("wb") as handle:
        handle.write(markdown.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    fsync_directory(directory)
    return str(path)


def markdown_report(
    genkey_value: str,
    results: str | None = None,
    ppl: str | None = None,
    criterion: float | None = None,
    flowpath: str | None = None,
    pipe: str | None = None,
    title: str | None = None,
    verdicts: list[dict[str, Any]] | None = None,
    figures: list[str] | None = None,
) -> dict[str, Any]:
    genkey = require_genkey_path(genkey_value)
    inputs: list[tuple[str, Path]] = [("genkey", genkey)]
    args = [str(genkey)]
    if results:
        results_path = require_fluid_path(results, {".tpl", ".ppl"})
        inputs.append(("results", results_path))
        args.extend(["--results", str(results_path)])
    if criterion is not None:
        if not ppl or not flowpath or not pipe:
            raise OlgaInputError("A criterion report requires ppl, flowpath, and pipe.")
        ppl_path = require_fluid_path(ppl, {".ppl"})
        inputs.append(("ppl", ppl_path))
        args.extend(
            [
                "--ppl", str(ppl_path),
                "--criterion", str(float(criterion)),
                "--flowpath", _token(flowpath, "flowpath"),
                "--pipe", _token(pipe, "pipe"),
            ]
        )
    if title:
        cleaned = "".join(ch for ch in title if ch.isalnum() or ch in " -_()").strip().lstrip("-").strip()
        if cleaned:
            args.extend(["--title", cleaned])

    hashes = {label: file_sha256(path) for label, path in inputs}
    out_dir = _report_dir()
    out = out_dir / "report.md"
    args.extend(["-o", str(out)])
    command = run_tool("report_generator", args, timeout_s=REPORT_TIMEOUT_S, names=REPORT_SCRIPTS)

    sources = [_source_evidence(label, path, hashes[label]) for label, path in inputs]
    verdict_list = _checked_verdicts(verdicts)
    figure_list = _checked_figures(figures)
    embedded_failures: list[str] = []
    if out.exists():
        text = out.read_text(encoding="utf-8", errors="replace")
        embedded_failures = embedded_failure_markers(text)
        body = text
        if verdict_list or figure_list:
            extra = ["", _verdict_section(verdict_list).rstrip()]
            if figure_list:
                extra.extend(["", _figure_section(figure_list).rstrip()])
            body = text.rstrip() + "\n" + "\n".join(extra)
        out.write_text(
            body + "\n".join(_sources_lines(sources, verdict_list)) + "\n",
            encoding="utf-8",
        )
    else:
        shutil.rmtree(out_dir, ignore_errors=True)

    ok = command.exit_code == 0 and out.exists() and not embedded_failures
    return {
        "ok": ok,
        "report": str(out) if out.exists() else None,
        "embedded_failures": embedded_failures,
        "sources": sources,
        "command": command.to_dict(),
    }


def generate_figure(
    kind: str,
    file_value: str,
    branch: str,
    criterion: float | None = None,
    timestep: float | None = None,
) -> dict[str, Any]:
    suffixes = FIGURE_KINDS.get(kind)
    if suffixes is None:
        raise OlgaInputError(f"Unknown figure kind: {kind!r}. Choose one of: {', '.join(sorted(FIGURE_KINDS))}")
    source = require_fluid_path(file_value, suffixes)
    before = file_sha256(source)
    out_dir = _report_dir()
    out = out_dir / f"{kind}.png"
    args = [kind, str(source), "--branch", _token(branch, "branch"), "-o", str(out)]
    if timestep is not None and kind == "hol-profile":
        args.extend(["--timestep", str(float(timestep))])
    if criterion is not None and kind == "liqc-timeseries":
        args.extend(["--criterion", str(float(criterion))])
    command = run_tool("figure_generator", args, timeout_s=REPORT_TIMEOUT_S, names=REPORT_SCRIPTS)
    ok = command.exit_code == 0 and out.exists()
    if not ok:
        shutil.rmtree(out_dir, ignore_errors=True)
    return {
        "ok": ok,
        "kind": kind,
        "figure": str(out) if ok else None,
        "command": command.to_dict(),
        "sources": [_source_evidence("result", source, before)],
    }


def compare_cases(
    files: list[str],
    labels: list[str] | None = None,
    variables: list[str] | None = None,
    branch: str | None = None,
    timestep: float | None = None,
) -> dict[str, Any]:
    if len(files) < 2:
        raise OlgaInputError("Comparison requires at least two result files.")
    # The comparator's .ppl mode ignores --json entirely, so only .tpl inputs
    # can produce a machine-readable package.
    paths = [require_fluid_path(value, {".tpl"}) for value in files]
    hashes = [file_sha256(path) for path in paths]
    args = [str(path) for path in paths]
    if labels:
        if len(labels) != len(paths):
            raise OlgaInputError("labels must match the number of files.")
        args.extend(["--labels", ",".join(_token(label, "label") for label in labels)])
    if variables:
        args.extend(["--vars", ",".join(_token(name, "variable") for name in variables)])
    if branch:
        args.extend(["--branch", _token(branch, "branch")])
    if timestep is not None:
        args.extend(["--timestep", str(float(timestep))])
    args.append("--json")
    command = run_tool("result_comparator", args, timeout_s=REPORT_TIMEOUT_S, names=REPORT_SCRIPTS)
    start = command.stdout.find("[")
    comparison = None
    if start >= 0:
        try:
            comparison = json.loads(command.stdout[start:])
        except json.JSONDecodeError:
            comparison = None
    ok = command.exit_code == 0 and isinstance(comparison, list)
    return {
        "ok": ok,
        "comparison": comparison or [],
        "command": command.to_dict(),
        "sources": [
            _source_evidence(f"case_{index}", path, before)
            for index, (path, before) in enumerate(zip(paths, hashes))
        ],
    }
