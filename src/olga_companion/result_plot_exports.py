from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .genkey_static import CommandResult, OlgaInputError
from .result_export_paths import ExportsRoot, create_export_dir
from .result_provenance import ensure_result_source_unchanged

HashFile = Callable[[Path], str]
PublicationRenderer = Callable[[dict[str, Any], Path], dict[str, Any]]
ResolveResult = Callable[[str], Path]
RunTool = Callable[..., CommandResult]
SeriesReader = Callable[..., dict[str, Any]]
TokenValidator = Callable[[list[str], str], list[str]]


_PROFILE_TIME = re.compile(r"_t(\d+(?:\.\d+)?)\.png$")


def _profile_at(plots: list[str], timestep: float | None) -> str | None:
    """The per-timestep profile PNG nearest to timestep, or the last time when none is asked."""
    timed = [(float(match.group(1)), plot) for plot in plots if (match := _PROFILE_TIME.search(plot))]
    if not timed:
        return None
    if timestep is None:
        return max(timed)[1]
    return min(timed, key=lambda item: abs(item[0] - timestep))[1]


def plot_result(
    path_value: str,
    variables: list[str] | None,
    branch: str | None,
    position: str | None,
    *,
    value_unit: str | None,
    time_unit: str | None,
    quantity_kind: str,
    range_spec: dict[str, Any] | None,
    timestep: float | None = None,
    resolve_result: ResolveResult,
    hash_file: HashFile,
    exports_root: ExportsRoot,
    require_tokens: TokenValidator,
    series_reader: SeriesReader,
    publication_renderer: PublicationRenderer,
    run_tool: RunTool,
    result_scripts: dict[str, str],
    plot_timeout_s: int,
) -> dict[str, Any]:
    path = resolve_result(path_value)
    before = hash_file(path)
    publication = None
    documents: list[str] = []
    series = None
    tpl_variables: list[str] | None = None
    ppl_variable: str | None = None
    ppl_branch: str | None = None
    if path.suffix.lower() == ".tpl" and position:
        if not variables or len(variables) != 1:
            raise OlgaInputError("A publication trend requires exactly one variable and one position.")
        selected_variable = require_tokens(variables, "variable")[0]
        view_requested = (
            value_unit is not None
            or time_unit is not None
            or quantity_kind != "point"
            or range_spec is not None
        )
        if view_requested:
            series = series_reader(
                path_value,
                selected_variable,
                position,
                value_unit=value_unit,
                time_unit=time_unit,
                quantity_kind=quantity_kind,
                range_spec=range_spec,
            )
        else:
            series = series_reader(path_value, selected_variable, position)
    elif path.suffix.lower() == ".tpl":
        if value_unit is not None or time_unit is not None or quantity_kind != "point" or range_spec is not None:
            raise OlgaInputError("Result view options require a single position-selected publication trend.")
        if variables:
            tpl_variables = require_tokens(variables, "variable")
    else:
        if value_unit is not None or time_unit is not None or quantity_kind != "point" or range_spec is not None:
            raise OlgaInputError("Result view options require a single position-selected publication trend.")
        if not branch or not variables:
            raise OlgaInputError("Plotting a .ppl profile requires both a branch and one variable.")
        if len(variables) > 1:
            raise OlgaInputError("Plotting a .ppl profile supports exactly one variable per request.")
        ppl_branch = require_tokens([branch], "branch")[0]
        ppl_variable = require_tokens(variables, "variable")[0]

    request_export_root = create_export_dir(exports_root)
    out_dir = request_export_root / "plots"
    completed = False
    try:
        out_dir.mkdir(parents=True, exist_ok=False)
        if series is not None:
            publication = publication_renderer(series, out_dir)
            plots = [publication["png"]]
            documents = [publication["pdf"]]
            command = None
        elif path.suffix.lower() == ".tpl":
            args = [str(path), "--out-dir", str(out_dir)]
            if tpl_variables:
                args.extend(["--vars", ",".join(tpl_variables)])
            command = run_tool(
                "fast_plotter",
                args,
                timeout_s=plot_timeout_s,
                names=result_scripts,
            )
        else:
            assert ppl_branch is not None and ppl_variable is not None
            args = [
                str(path),
                "--branch", ppl_branch,
                "--var", ppl_variable,
                "--all-timesteps",
                "--out-dir", str(out_dir),
            ]
            command = run_tool(
                "fast_ppl_plotter",
                args,
                timeout_s=plot_timeout_s,
                names=result_scripts,
            )
        if publication is None:
            plots = sorted(str(png) for png in out_dir.glob("*.png"))
        selected_plot = _profile_at(plots, timestep) if ppl_variable is not None else None
        after = ensure_result_source_unchanged(
            path,
            before,
            hash_file,
            discard_root=request_export_root,
        )
        completed = True
    finally:
        if not completed:
            shutil.rmtree(request_export_root, ignore_errors=True)
    return {
        "path": str(path),
        "ok": bool(plots) if publication else command.exit_code == 0 and bool(plots),
        "plots": plots,
        "selected_plot": selected_plot,
        "documents": documents,
        "publication": publication,
        "analysis": series["analysis"] if publication else None,
        "view": series["view"] if publication else None,
        "command": command.to_dict() if command else None,
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": False,
    }
