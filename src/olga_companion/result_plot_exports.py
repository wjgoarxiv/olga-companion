from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .genkey_static import CommandResult, OlgaInputError
from .result_export_paths import ExportsRoot, create_export_dir
from .result_provenance import ensure_result_source_unchanged
from .units import convert_values

HashFile = Callable[[Path], str]
PublicationRenderer = Callable[[dict[str, Any], Path], dict[str, Any]]
ResolveResult = Callable[[str], Path]
RunTool = Callable[..., CommandResult]
ProfileReader = Callable[..., dict[str, Any]]
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


def _profile_view(
    read: ProfileReader, path_value: str, variable: str, branch: str, timestep: float | None, value_unit: str | None
) -> dict[str, Any]:
    """One profile in the asked unit, with its undefined sections left as gaps; a unit that does not fit is refused."""
    profile = read(path_value, variable, branch, timestep)
    raw = profile["values"]
    defined = [index for index, value in enumerate(raw) if value is not None and profile["positions"][index] is not None]
    if not defined:
        raise OlgaInputError("The profile has no defined values at this time.")
    converted = convert_values([raw[index] for index in defined], profile.get("unit"), value_unit)
    if converted["conversion"]["status"] == "source_only":
        raise OlgaInputError(f"Cannot convert {variable} from {profile.get('unit') or 'no unit'} to {value_unit}.")
    values: list[float | None] = [None] * len(raw)
    for index, value in zip(defined, converted["values"], strict=True):
        values[index] = value
    return {**profile, "values": values, "unit": converted["unit"]}


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
    profile_pdf: bool = False,
    profile_reader: ProfileReader | None = None,
    profile_renderer: PublicationRenderer | None = None,
) -> dict[str, Any]:
    path = resolve_result(path_value)
    before = hash_file(path)
    publication = None
    documents: list[str] = []
    series = None
    profile = None
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
        if time_unit is not None or quantity_kind != "point" or range_spec is not None:
            raise OlgaInputError("A .ppl profile shows one time: pick it with timestep. Its value unit can be chosen.")
        if not branch or not variables:
            raise OlgaInputError("Plotting a .ppl profile requires both a branch and one variable.")
        if len(variables) > 1:
            raise OlgaInputError("Plotting a .ppl profile supports exactly one variable per request.")
        ppl_branch = require_tokens([branch], "branch")[0]
        ppl_variable = require_tokens(variables, "variable")[0]
        if value_unit is not None or profile_pdf:
            assert profile_reader is not None
            profile = _profile_view(profile_reader, path_value, ppl_variable, ppl_branch, timestep, value_unit)

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
        elif profile is not None:
            assert profile_renderer is not None
            publication = profile_renderer(profile, out_dir)
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
                "--png",
                "--out-dir", str(out_dir),
            ]
            if timestep is not None:
                args.extend(["--timestep", str(float(timestep))])
            command = run_tool(
                "fast_ppl_plotter",
                args,
                timeout_s=plot_timeout_s,
                names=result_scripts,
            )
        if publication is None:
            plots = sorted(str(png) for png in out_dir.glob("*.png"))
        selected_plot = None
        if ppl_variable is not None:
            selected_plot = plots[0] if publication else _profile_at(plots, timestep)
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
        "analysis": series["analysis"] if series else None,
        "view": series["view"] if series else None,
        "command": command.to_dict() if command else None,
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_mutated": False,
    }
