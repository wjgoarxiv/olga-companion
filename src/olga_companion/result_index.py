from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .genkey_static import CommandResult

RunTool = Callable[..., CommandResult]


def parse_json(stdout: str) -> Any:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def parse_index(
    path: Path,
    *,
    run_tool: RunTool,
    result_scripts: dict[str, str],
    timeout_s: int,
) -> dict[str, Any]:
    """Parse a result file's variable, branch, and timestep index."""
    file_type = path.suffix.lower().lstrip(".")
    vars_command = run_tool(
        "result_parser",
        [str(path), "--list-vars", "--json"],
        timeout_s=timeout_s,
        names=result_scripts,
    )
    variables = parse_json(vars_command.stdout)
    ok = vars_command.exit_code == 0 and isinstance(variables, list)
    index: dict[str, Any] = {
        "file_type": file_type,
        "ok": ok,
        "variables": variables if isinstance(variables, list) else [],
        "parser": vars_command.to_dict(),
    }
    first = index["variables"][0] if index["variables"] else None
    if ok and file_type == "tpl" and isinstance(first, dict) and first.get("variable"):
        series = run_tool(
            "result_parser",
            [str(path), "-v", first["variable"], "--json"],
            timeout_s=timeout_s,
            names=result_scripts,
        )
        parsed = parse_json(series.stdout)
        time = parsed.get("time") if isinstance(parsed, dict) else None
        if isinstance(time, list) and time:
            index["time_range"] = {
                "start_s": time[0],
                "end_s": time[-1],
                "samples": len(time),
            }
    if ok and file_type == "ppl":
        branches = run_tool(
            "result_parser",
            [str(path), "--list-branches", "--json"],
            timeout_s=timeout_s,
            names=result_scripts,
        )
        timesteps = run_tool(
            "result_parser",
            [str(path), "--list-timesteps", "--json"],
            timeout_s=timeout_s,
            names=result_scripts,
        )
        index["ok"] = branches.exit_code == 0 and timesteps.exit_code == 0
        index["branches"] = parse_json(branches.stdout) or []
        index["timesteps"] = parse_json(timesteps.stdout) or []
        index["branches_command"] = branches.to_dict()
        index["timesteps_command"] = timesteps.to_dict()
    return index
