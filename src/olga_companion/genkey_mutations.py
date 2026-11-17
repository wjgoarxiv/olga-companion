from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def _facade() -> Any:
    from . import genkey_static

    return genkey_static


def create_and_save(
    save_path: str,
    topology: str,
    endtime_s: int = 3600,
    pvtfile: str = "./fluid.tab",
) -> dict[str, Any]:
    facade = _facade()
    if topology not in facade.ALLOWED_TOPOLOGIES:
        choices = ", ".join(sorted(facade.ALLOWED_TOPOLOGIES))
        raise facade.OlgaInputError(
            f"Unknown topology {topology!r}. Choose one of: {choices}"
        )
    output = Path(save_path).expanduser().resolve()
    if output.suffix.lower() != ".genkey":
        raise facade.OlgaInputError("The save path must end in .genkey.")
    if not output.parent.is_dir():
        raise facade.OlgaInputError("The selected save folder does not exist.")
    result = facade.run_tool(
        "builder",
        [
            topology,
            "--endtime",
            str(endtime_s),
            "--pvtfile",
            pvtfile,
            "--save",
            str(output),
        ],
    )
    saved = output.exists()
    validation = facade.run_tool("validator", [str(output)]) if saved else None
    return {
        "topology": topology,
        "saved_path": str(output) if saved else None,
        "ok": result.exit_code == 0 and saved,
        "valid": validation.exit_code == 0 if validation else False,
        "command": result.to_dict(),
    }


def json_after_noise(stdout: str) -> Any:
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip()[:1] not in ("[", "{"):
            continue
        try:
            return json.loads("\n".join(lines[index:]))
        except (json.JSONDecodeError, RecursionError):
            continue
    return None


def sweep_preview(
    base_path: str,
    sweeps: list[str],
    strategy: str = "oat",
    max_cases: int = 20,
) -> dict[str, Any]:
    facade = _facade()
    base = facade.require_genkey_path(base_path)
    if strategy not in ("oat", "cartesian"):
        raise facade.OlgaInputError("strategy must be 'oat' or 'cartesian'.")
    if not sweeps:
        raise facade.OlgaInputError(
            "At least one sweep spec is required (KEYWORD.KEY=v1,v2,v3)."
        )
    if any("=" not in spec or spec.startswith("-") for spec in sweeps):
        raise facade.OlgaInputError(
            "Invalid sweep spec; expected KEYWORD.KEY=v1,v2,v3."
        )
    output_dir = facade._run_dir(base)
    args = [
        str(base),
        "--strategy",
        strategy,
        "--max-cases",
        str(int(max_cases)),
        "--dry-run",
        "--json",
        "--output-dir",
        str(output_dir),
    ]
    for spec in sweeps:
        args.extend(["--sweep", spec])
    result = facade.run_tool("sweep", args, timeout_s=120)
    parsed = json_after_noise(result.stdout) if result.exit_code == 0 else None
    return {
        "base": str(base),
        "strategy": strategy,
        "sweeps": sweeps,
        "dry_run": True,
        "ok": result.exit_code == 0 and parsed is not None,
        "plan": parsed if parsed is not None else result.stdout,
        "output_dir": str(output_dir),
        "command": result.to_dict(),
    }


def modify_copy(
    source_value: str,
    keyword: str,
    key: str,
    value: str,
    label: str | None = None,
) -> dict[str, Any]:
    facade = _facade()
    source = facade.require_genkey_path(source_value)
    if not keyword.strip() or not key.strip() or not value.strip():
        raise facade.OlgaInputError(
            "keyword, key, and value are required for modify-copy."
        )
    before_hash = facade.file_sha256(source)
    run_dir = facade._run_dir(source)
    working_copy = run_dir / source.name
    modified = run_dir / f"{source.stem}.modified.genkey"
    backup = working_copy.with_suffix(working_copy.suffix + ".bak")
    shutil.copy2(source, working_copy)
    shutil.copy2(working_copy, backup)
    args = [
        str(working_copy),
        keyword.strip(),
        key.strip(),
        value.strip(),
        "--output",
        str(modified),
    ]
    if label and label.strip():
        args.extend(["--label", label.strip()])
    write = facade.run_tool("writer", args)
    validation = _followup_or_skipped("validator", source, modified)
    diff = _followup_or_skipped("diff", source, modified)
    after_hash = facade.file_sha256(source)
    return {
        "source": str(source),
        "sandbox_dir": str(run_dir),
        "working_copy": str(working_copy),
        "modified_copy": str(modified) if modified.exists() else None,
        "backup": str(backup),
        "source_sha256_before": before_hash,
        "source_sha256_after": after_hash,
        "source_mutated": before_hash != after_hash,
        "valid": validation.exit_code == 0,
        "write": write.to_dict(),
        "validation": validation.to_dict(),
        "diff": diff.to_dict(),
    }


def _followup_or_skipped(operation: str, source: Path, modified: Path) -> Any:
    facade = _facade()
    args = [str(modified)] if operation == "validator" else [str(source), str(modified)]
    if modified.exists():
        return facade.run_tool(operation, args)
    return facade.CommandResult(
        script=facade.SCRIPT_NAMES[operation],
        args=args,
        exit_code=2,
        stdout="",
        stderr=f"Modified file was not created; {operation} skipped.",
        timed_out=False,
        elapsed_ms=0,
    )
