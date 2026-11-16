from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import toolkit_dir
from .genkey_static import OlgaInputError, file_sha256, require_genkey_path, run_tool

FLUID_SCRIPTS = {
    "tab_parser": "tab_parser.py",
    "tab_summarizer": "tab_summarizer.py",
    "tab_validator": "tab_validator.py",
    "mfl_parser": "mfl_parser.py",
    # Detection only (--status). M2 never executes Multiflash.
    "mfl_runner": "mfl_runner.py",
}

PVTFILE_PATTERN = re.compile(r'PVTFILE\s*=\s*(?:"([^"]+)"|(\S+))', re.IGNORECASE)


def fluids_toolkit_status() -> dict[str, Any]:
    root = toolkit_dir()
    scripts = {name: (root / "scripts" / script).exists() for name, script in FLUID_SCRIPTS.items()}
    return {
        "toolkit_dir": str(root),
        "available": root.exists() and all(scripts.values()),
        "scripts": scripts,
    }


def require_fluid_path(path_value: str, suffixes: set[str]) -> Path:
    if not path_value or not path_value.strip():
        raise OlgaInputError("A file path is required.")
    path = Path(path_value).expanduser().resolve()
    if path.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise OlgaInputError(f"Only {allowed} files are accepted for this route.")
    if not path.exists():
        raise OlgaInputError(f"File not found: {path}")
    if not path.is_file():
        raise OlgaInputError(f"Path is not a file: {path}")
    return path


def _parse_json_stdout(stdout: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_tab(path: Path, genkey: Path | None = None) -> dict[str, Any]:
    # Neither an exit code alone nor an incomplete report proves that the table was checked.
    args = [str(path)]
    if genkey is not None:
        args.extend(["--genkey", str(genkey)])
    args.append("--json")
    command = run_tool("tab_validator", args, names=FLUID_SCRIPTS)
    report = _parse_json_stdout(command.stdout)
    structured = (
        report is not None
        and isinstance(report.get("errors"), list)
        and isinstance(report.get("warnings"), list)
    )
    errors = list(report["errors"]) if structured else []
    warnings = list(report["warnings"]) if structured else []
    completed = command.exit_code == 0 and not command.timed_out
    if (not structured or not completed) and not errors:
        errors = [{
            "rule_id": "V000",
            "severity": "ERROR",
            "category": "parse",
            "message": "PVT validation did not return a complete, successful report.",
        }]
    return {
        "valid": structured and completed and not errors,
        "errors": errors,
        "warnings": warnings,
        "command": command.to_dict(),
    }


def inspect_tab(path_value: str) -> dict[str, Any]:
    path = require_fluid_path(path_value, {".tab"})
    before = file_sha256(path)
    parser = run_tool("tab_parser", [str(path), "--json"], names=FLUID_SCRIPTS)
    summary = run_tool("tab_summarizer", [str(path)], names=FLUID_SCRIPTS)
    validation = _validate_tab(path)
    after = file_sha256(path)
    return {
        "path": str(path),
        "valid": validation["valid"],
        "parsed": _parse_json_stdout(parser.stdout),
        "summary_text": summary.stdout,
        "validation_errors": validation["errors"],
        "validation_warnings": validation["warnings"],
        "parser": parser.to_dict(),
        "summarizer": summary.to_dict(),
        "validator": validation["command"],
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": before != after,
    }


def inspect_mfl(path_value: str) -> dict[str, Any]:
    path = require_fluid_path(path_value, {".mfl"})
    before = file_sha256(path)
    parser = run_tool("mfl_parser", ["--json", str(path)], names=FLUID_SCRIPTS)
    summary = run_tool("mfl_parser", [str(path)], names=FLUID_SCRIPTS)
    parsed = _parse_json_stdout(parser.stdout)
    after = file_sha256(path)
    return {
        "path": str(path),
        "ok": parser.exit_code == 0 and parsed is not None,
        "parsed": parsed,
        "summary_text": summary.stdout,
        "parser": parser.to_dict(),
        "summarizer": summary.to_dict(),
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": before != after,
    }


def consistency(path_value: str) -> dict[str, Any]:
    genkey = require_genkey_path(path_value)
    before = file_sha256(genkey)
    text = genkey.read_text(encoding="utf-8", errors="replace")
    references: list[dict[str, Any]] = []
    for match in PVTFILE_PATTERN.finditer(text):
        raw = match.group(1) or match.group(2)
        candidate = Path(raw)
        resolved = candidate if candidate.is_absolute() else (genkey.parent / candidate).resolve()
        exists = resolved.is_file()
        cross_check = None
        if exists and resolved.suffix.lower() == ".tab":
            cross_check = _validate_tab(resolved, genkey=genkey)
        references.append(
            {
                "raw": raw,
                "resolved": str(resolved),
                "exists": exists,
                "cross_check": cross_check,
            }
        )
    after = file_sha256(genkey)
    return {
        "genkey": str(genkey),
        "references": references,
        "total": len(references),
        "missing": sum(1 for reference in references if not reference["exists"]),
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": before != after,
    }


def multiflash_detection() -> dict[str, Any]:
    command = run_tool("mfl_runner", ["--status"], timeout_s=15, names=FLUID_SCRIPTS)
    output = f"{command.stdout}\n{command.stderr}".upper()
    detected = "STATUS:" in output and "NOT FOUND" not in output
    return {"detected": detected, "command": command.to_dict()}


def fluid_capabilities() -> dict[str, Any]:
    status = fluids_toolkit_status()
    detection = multiflash_detection() if status["scripts"].get("mfl_runner") else {"detected": False}
    if detection["detected"]:
        multiflash_reason = (
            "Multiflash CLI detected, but execution stays gated to manual-export mode "
            "until a tested table-generation workflow exists."
        )
    else:
        multiflash_reason = (
            "No supported Multiflash CLI detected; .mfl/.tab files can be inspected "
            "and prepared in manual-export mode only."
        )
    return {
        "fluid_pvt_static": {
            "enabled": status["available"],
            "reason": "Fluid/PVT toolkit scripts detected." if status["available"] else "Required fluid/PVT toolkit scripts are missing.",
        },
        "multiflash": {
            "enabled": False,
            "reason": multiflash_reason,
        },
    }
