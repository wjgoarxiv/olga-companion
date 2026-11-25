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
    # One call: the installed app pays seconds for every start of the parser.
    command = run_tool("result_parser", [str(path), "--index", "--json"], timeout_s=timeout_s, names=result_scripts)
    parsed = parse_json(command.stdout)
    found = parsed if isinstance(parsed, dict) else {}
    variables = found.get("variables")
    index: dict[str, Any] = {
        "file_type": file_type,
        "ok": command.exit_code == 0 and isinstance(variables, list),
        "variables": variables if isinstance(variables, list) else [],
        "parser": command.to_dict(),
    }
    if found.get("time_range"):
        index["time_range"] = found["time_range"]
    if index["ok"] and file_type == "ppl":
        index["branches"] = found.get("branches") or []
        index["timesteps"] = found.get("timesteps") or []
    return index
