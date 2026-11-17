from __future__ import annotations

import json
import subprocess as subprocess
import uuid
from pathlib import Path
from typing import Any

from . import genkey_mutations as _mutations
from . import genkey_network as _network
from . import genkey_tool_runner as _runner
from .config import sandbox_root, toolkit_dir

SCRIPT_NAMES = {
    "builder": "genkey_builder.py",
    "summarizer": "genkey_summarizer.py",
    "validator": "genkey_validator.py",
    "writer": "genkey_writer.py",
    "diff": "genkey_diff.py",
    "topology": "topology_visualizer.py",
    "parser": "genkey_parser.py",
    "opi_parser": "opi_parser.py",
    "pipe_mapper": "pipe_mapper.py",
    "sweep": "parametric_sweep.py",
}

ALLOWED_TOPOLOGIES = {
    "simple_pipeline",
    "production_well",
    "well_pipeline",
    "subsea_tieback",
    "riser",
    "separator",
}
# The flowpath view parses the whole case document, exactly as the topology
# graph does, so it needs the same budget. A stricter cap here meant a real
# 420 KB case rendered its graph and then failed the moment a flowpath was
# clicked. Kept as a named constant so the two can diverge deliberately later.
FLOWPATH_TOOL_OUTPUT_BYTES = _runner.DEFAULT_TOOL_OUTPUT_BYTES
MAX_GENKEY_INPUT_BYTES = 64 * 1024 * 1024
TOOL_OUTPUT_LIMIT_EXIT_CODE = _runner.TOOL_OUTPUT_LIMIT_EXIT_CODE
_MAX_GRAPH_EDGES = _network.MAX_GRAPH_EDGES
CommandResult = _runner.CommandResult


class OlgaInputError(ValueError):
    """User-correctable input error at a sidecar trust boundary."""


def _script_path(
    script_key: str,
    names: dict[str, str] | None = None,
) -> Path:
    return _runner.script_path(
        script_key,
        names or SCRIPT_NAMES,
        toolkit_dir(),
        OlgaInputError,
    )


def toolkit_status() -> dict[str, Any]:
    return _runner.toolkit_status(toolkit_dir(), SCRIPT_NAMES)


def run_tool(
    script_key: str,
    args: list[str],
    timeout_s: int = 30,
    names: dict[str, str] | None = None,
    *,
    max_output_bytes: int = _runner.DEFAULT_TOOL_OUTPUT_BYTES,
) -> CommandResult:
    mapping = names or SCRIPT_NAMES
    return _runner.run_tool(
        script_key,
        args,
        timeout_s=timeout_s,
        mapping=mapping,
        resolve_script=_script_path,
        cwd=toolkit_dir(),
        max_output_bytes=max_output_bytes,
    )


file_sha256 = _runner.file_sha256


def require_genkey_path(path_value: str) -> Path:
    if not path_value or not path_value.strip():
        raise OlgaInputError("A .genkey file path is required.")
    path = Path(path_value).expanduser().resolve()
    if path.name.startswith("-"):
        raise OlgaInputError("Case file names must not start with '-'.")
    if path.suffix.lower() != ".genkey":
        raise OlgaInputError("Only .genkey files are accepted for this route.")
    if not path.exists():
        raise OlgaInputError(f"File not found: {path}")
    if not path.is_file():
        raise OlgaInputError(f"Path is not a file: {path}")
    if path.stat().st_size > MAX_GENKEY_INPUT_BYTES:
        raise OlgaInputError("The .genkey file exceeds the input size limit (64 MiB).")
    return path


def create_preview(
    topology: str,
    endtime_s: int = 3600,
    pvtfile: str = "./fluid.tab",
) -> dict[str, Any]:
    if topology not in ALLOWED_TOPOLOGIES:
        choices = ", ".join(sorted(ALLOWED_TOPOLOGIES))
        raise OlgaInputError(f"Unknown topology {topology!r}. Choose one of: {choices}")
    if endtime_s <= 0:
        raise OlgaInputError("endtime_s must be positive.")
    if not pvtfile.strip():
        raise OlgaInputError("pvtfile is required.")
    result = run_tool(
        "builder",
        [topology, "--endtime", str(endtime_s), "--pvtfile", pvtfile, "--no-validate"],
    )
    return {
        "topology": topology,
        "endtime_s": endtime_s,
        "pvtfile": pvtfile,
        "preview": result.stdout,
        "command": result.to_dict(),
        "ok": result.exit_code == 0 and bool(result.stdout.strip()),
    }


def review_file(path_value: str) -> dict[str, Any]:
    path = require_genkey_path(path_value)
    source_sha256 = file_sha256(path)
    validation = run_tool("validator", [str(path)]).to_dict()
    summary = run_tool("summarizer", [str(path)]).to_dict()
    topology = run_tool("topology", [str(path)])
    validation["source_sha256"] = source_sha256
    summary["source_sha256"] = source_sha256
    return {
        "path": str(path),
        "source_sha256": source_sha256,
        "valid": validation["exit_code"] == 0,
        "validation": validation,
        "summary": summary,
        "topology": topology.to_dict(),
    }


def parse_network(path_value: str) -> dict[str, Any]:
    return _network.parse_network(
        path_value,
        require_path=require_genkey_path,
        run_tool=run_tool,
        input_error=OlgaInputError,
    )


_network_from_parsed = _network.network_from_parsed


def diff_cases(path_a: str, path_b: str) -> dict[str, Any]:
    first = require_genkey_path(path_a)
    second = require_genkey_path(path_b)
    result = run_tool("diff", [str(first), str(second)])
    return {
        "path_a": str(first),
        "path_b": str(second),
        "diff": result.stdout,
        "ok": result.exit_code == 0,
        "command": result.to_dict(),
    }


def _require_suffix_path(path_value: str, suffix: str) -> Path:
    if not path_value or not path_value.strip():
        raise OlgaInputError("A file path is required.")
    path = Path(path_value).expanduser().resolve()
    if path.name.startswith("-"):
        raise OlgaInputError("File names must not start with '-'.")
    if path.suffix.lower() != suffix:
        raise OlgaInputError(f"Only {suffix} files are accepted for this route.")
    if not path.is_file():
        raise OlgaInputError(f"File not found: {path}")
    return path


def parse_opi(path_value: str) -> dict[str, Any]:
    path = _require_suffix_path(path_value, ".opi")
    result = run_tool("opi_parser", [str(path), "--json"])
    try:
        parsed = json.loads(result.stdout) if result.exit_code == 0 else None
    except (json.JSONDecodeError, RecursionError):
        parsed = None
    return {
        "path": str(path),
        "ok": result.exit_code == 0 and parsed is not None,
        "parsed": parsed,
        "command": result.to_dict(),
    }


_PIPE_OPS = {
    "list_pipes": "--list-pipes",
    "sections": "--sections",
    "volume": "--volume",
    "elevation_profile": "--elevation-profile",
    "lowest_point": "--lowest-point",
}


def pipe_geometry(
    path_value: str,
    flowpath: str,
    op: str = "list_pipes",
) -> dict[str, Any]:
    path = require_genkey_path(path_value)
    if not flowpath or not flowpath.strip():
        raise OlgaInputError("A flowpath TAG/LABEL is required.")
    flag = _PIPE_OPS.get(op)
    if flag is None:
        choices = ", ".join(sorted(_PIPE_OPS))
        raise OlgaInputError(f"Unknown op {op!r}. Choose one of: {choices}")
    result = run_tool(
        "pipe_mapper",
        [str(path), flowpath, flag, "--json"],
        max_output_bytes=FLOWPATH_TOOL_OUTPUT_BYTES,
    )
    if result.exit_code == TOOL_OUTPUT_LIMIT_EXIT_CODE:
        raise OlgaInputError("Flowpath geometry exceeds the supported output limit.")
    try:
        parsed = json.loads(result.stdout) if result.exit_code == 0 else None
    except (json.JSONDecodeError, RecursionError):
        parsed = None
    return {
        "path": str(path),
        "flowpath": flowpath,
        "op": op,
        "ok": result.exit_code == 0 and parsed is not None,
        "result": parsed if parsed is not None else result.stdout,
        "command": result.to_dict(),
    }


def _run_dir(source: Path) -> Path:
    safe_stem = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in source.stem
    )[:80]
    path = sandbox_root() / f"{safe_stem}-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


create_and_save = _mutations.create_and_save
_json_after_noise = _mutations.json_after_noise
sweep_preview = _mutations.sweep_preview
modify_copy = _mutations.modify_copy


def capabilities() -> dict[str, Any]:
    status = toolkit_status()
    return {
        "static_genkey": {
            "enabled": status["available"],
            "reason": (
                "OLGA toolkit scripts detected."
                if status["available"]
                else "Required static GENKEY toolkit scripts are missing."
            ),
        },
        "live_olga_run": {
            "enabled": False,
            "reason": "Gated until executable detection and explicit approval exist.",
        },
        "multiflash": {
            "enabled": False,
            "reason": "Gated until a supported Multiflash workflow is verified.",
        },
        "result_analysis": {
            "enabled": False,
            "reason": "Gated until result parser dependencies are verified.",
        },
        "opc_live_control": {
            "enabled": False,
            "reason": "Gated until OPC dependencies and write approval are verified.",
        },
    }
