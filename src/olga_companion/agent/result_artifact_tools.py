from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import reports, result_artifacts, results, workspace
from .tool_validation import DEFAULT_PATH_BINDINGS as DEFAULT_PATHS
from .tool_validation import PathBindings, ToolError


def _result_id(value: str) -> str:
    from .result_tools import canonical_result_id

    return canonical_result_id(value)


def _lineage(
    result_id: str,
    source_hash: str,
    operation: str,
) -> result_artifacts.ArtifactLineage:
    return {
        "source_kind": result_id.partition(":")[0],
        "source_id": result_id,
        "source_sha256": source_hash,
        "operation": operation,
    }


def _receipt(
    path: str,
    kind: result_artifacts.ArtifactKind,
    lineage: result_artifacts.ArtifactLineage,
) -> dict[str, Any]:
    return result_artifacts.register(
        Path(path),
        kind=kind,
        lineage=lineage,
        workspace_generation=workspace.context_generation(),
    )


def _view_options(args: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for name in ("value_unit", "time_unit", "quantity_kind"):
        if args.get(name) is not None:
            options[name] = args[name]
    time_range = args.get("time_range")
    if isinstance(time_range, dict):
        options["range_spec"] = {
            "mode": "bounds",
            "start": time_range["start"],
            "end": time_range["end"],
        }
    return options


def csv_export(
    args: dict[str, Any],
    paths: PathBindings = DEFAULT_PATHS,
) -> dict[str, Any]:
    result_id = _result_id(str(args["path"]))
    source = paths.result_file(result_id)
    variables = args["variables"]
    position = args.get("position")
    view = _view_options(args)
    if position is not None:
        if len(variables) != 1:
            raise ToolError("A selected-series CSV requires exactly one variable.")
        output = results.export_selected_series_csv(
            source,
            variables[0],
            position,
            **view,
        )
    else:
        if view:
            raise ToolError("Result view options require a selected position.")
        output = results.extract_csv(
            source,
            variables,
            args.get("branch"),
            args.get("timestep"),
        )
    if not output.get("ok") or not output.get("csv"):
        raise ToolError("Result CSV export failed; no artifact was issued.")
    source_hash = str(
        output.get("source_sha256_before") or results.file_sha256(Path(source))
    )
    lineage = _lineage(result_id, source_hash, "results_csv")
    return _receipt(str(output["csv"]), "csv", lineage)


def plot_export(
    args: dict[str, Any],
    paths: PathBindings = DEFAULT_PATHS,
) -> dict[str, Any]:
    result_id = _result_id(str(args["path"]))
    source = paths.result_file(result_id)
    options = _view_options(args)
    if args.get("timestep") is not None and Path(source).suffix.casefold() == ".ppl":
        options["timestep"] = float(args["timestep"])
    output = results.plot_result(
        source,
        args.get("variables"),
        args.get("branch"),
        args.get("position"),
        **options,
    )
    if not output.get("ok"):
        raise ToolError("Result plot export failed; no artifact was issued.")
    kind = str(args.get("format", "png"))
    candidates = output.get("documents") if kind == "pdf" else output.get("plots")
    if kind not in {"png", "pdf"} or not isinstance(candidates, list) or not candidates:
        raise ToolError(f"Result plot did not produce the requested {kind} artifact.")
    source_hash = str(
        output.get("source_sha256_before") or results.file_sha256(Path(source))
    )
    lineage = _lineage(result_id, source_hash, "results_plot")
    chosen = output.get("selected_plot") if kind == "png" else None
    return _receipt(str(chosen or candidates[0]), kind, lineage)


def report_figure(
    args: dict[str, Any],
    paths: PathBindings = DEFAULT_PATHS,
) -> dict[str, Any]:
    result_id = _result_id(str(args["file"]))
    source = paths.result_file(result_id)
    before = results.file_sha256(Path(source))
    output = reports.generate_figure(
        str(args["kind"]),
        source,
        str(args["branch"]),
        args.get("criterion"),
        args.get("timestep"),
    )
    after = results.file_sha256(Path(source))
    source_records = output.get("sources")
    reported_mutation = isinstance(source_records, list) and any(
        isinstance(record, dict) and record.get("mutated") is True
        for record in source_records
    )
    if before != after or reported_mutation:
        raise ToolError("Report figure source changed while rendering; no artifact was issued.")
    figure = output.get("figure")
    if not output.get("ok") or not figure:
        raise ToolError("Report figure export failed; no artifact was issued.")
    lineage = _lineage(
        result_id,
        before,
        "report_figure",
    )
    return _receipt(str(figure), "png", lineage)
