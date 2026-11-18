"""Ungated allowlisted adapter calls for the agent tool belt."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .. import (
    case_spec_recovery,
    case_transactions,
    case_compiler,
    case_spec,
    diagnostics,
    evaluation as evaluation_adapter,
    fluids,
    genkey_static,
    reports,
    runner,
    sweep_execution,
    workspace,
)
from . import result_tools as _result_tools
from . import result_artifact_tools as _artifact_tools
from .case_tool_result_bounds import bounded_compile_result
from .tool_validation import (
    DEFAULT_PATH_BINDINGS as DEFAULT_PATHS,
    PathBindings,
    ToolError,
    ToolRefusedError,
)

ToolArgs = dict[str, Any]
ToolResult = dict[str, Any]


def genkey_create(args: ToolArgs) -> ToolResult:
    return genkey_static.create_preview(
        args["topology"],
        int(args.get("endtime_s", 3600)),
        args.get("pvtfile", "./fluid.tab"),
    )


def case_spec_validate(args: ToolArgs) -> ToolResult:
    """Validate model-authored data without rendering or writing GENKEY."""
    from .. import pvt_range

    planned = cast(ToolResult, cast(object, case_spec.validate_case_spec(args["spec"])))
    if planned["valid"]:
        planned["spec_hash"] = case_transactions.case_spec_hash(args["spec"])
        range_errors, range_warnings = pvt_range.check_casespec_reference(
            cast(dict[str, Any], planned["normalized"])
        )
        if range_errors:
            return cast(ToolResult, cast(object, {
                "valid": False,
                "publishable": False,
                "version": planned["version"],
                "normalized": None,
                "capabilities": planned["capabilities"],
                "errors": range_errors,
                "warnings": [],
            }))
        if range_warnings:
            planned["warnings"] = [*planned["warnings"], *range_warnings]
    return planned


def case_spec_compile(
    args: ToolArgs,
    paths: PathBindings = DEFAULT_PATHS,
) -> ToolResult:
    """Compile and round-trip one valid CaseSpec without publishing it."""
    planned = case_spec_validate(args)
    if not planned["valid"]:
        return cast(ToolResult, cast(object, planned))
    owner_value = args.get("owner_source")
    owner = paths.input_file(owner_value, {".genkey"}) if owner_value else None
    compiled = case_compiler.compile_case_spec(args["spec"], owner)
    normalized = cast(dict[str, Any], planned["normalized"])
    assert normalized is not None
    flowpaths = cast(list[dict[str, Any]], normalized["flowpaths"])
    nodes = cast(list[dict[str, Any]], normalized["nodes"])
    result: ToolResult = {
        **planned,
        "publishable": False,
        "compiled_text": compiled.text,
        "compiled_hash": compiled.sha256,
        "topology": {
            "nodes": [
                {"label": node["label"], "kind": node["kind"]}
                for node in nodes
            ],
            "edges": [
                {"from": item["from"], "to": item["to"], "flowpath": item["label"]}
                for item in flowpaths
            ],
        },
        "geometry": [
            {
                "flowpath": flowpath["label"],
                "pipe": pipe["label"],
                "centerline_m": pipe["centerline_m"],
                "diameter_m": pipe["diameter_m"],
                "sections": pipe["sections"],
            }
            for flowpath in flowpaths
            for pipe in flowpath["pipes"]
        ],
        "validation": {
            "clean": compiled.validation.clean,
            "parser_clean": compiled.validation.parser_clean,
            "validator_clean": compiled.validation.validator_clean,
            "diagnostics": list(compiled.validation.diagnostics),
        },
        "section_count": compiled.section_count,
        "companion_status": compiled.companion_status,
        "source_mutated": compiled.source_mutated,
        "warnings": [
            *planned["warnings"],
            *(
                {
                    "code": "pvt_companion_unverified",
                    "field": "pvt_reference",
                    "message": warning,
                    "guidance": "Verify the contained .tab companion before approved publish.",
                }
                for warning in compiled.warnings
            ),
        ],
    }
    return bounded_compile_result(planned, result)


def genkey_review(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    path = args.get("path") or workspace.active_path()
    if not path:
        raise ToolError(
            "No case path given and no active case set. Pick a case in the workspace or name one."
        )
    path = paths.input_file(path, {".genkey"})
    result = genkey_static.review_file(path)
    try:
        result["case_spec"] = case_spec_recovery.recover_case_spec(Path(path)).model_dump(mode="json")
    except case_spec_recovery.UnsupportedSourceError:
        result["case_spec"] = None
    paths.set_active_case(path)
    return result


def genkey_topology(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    path = args.get("path") or workspace.active_path()
    if not path:
        raise ToolError(
            "No case path given and no active case set. Pick a case in the workspace or name one."
        )
    path = paths.input_file(path, {".genkey"})
    result = genkey_static.parse_network(path)
    paths.set_active_case(path)
    return result


def genkey_modify(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    path = args.get("path") or workspace.active_path()
    if not path:
        raise ToolError(
            "No case path given and no active case set. Pick a case in the workspace or name one."
        )
    path = paths.input_file(path, {".genkey"})
    result = genkey_static.modify_copy(
        path,
        args["keyword"],
        args["key"],
        args["value"],
        args.get("label"),
    )
    target = result.get("modified_copy") or path
    refusal = paths.set_active_case(target)
    if refusal:
        result = dict(result)
        result["notice"] = refusal
    return result


def genkey_diff(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return genkey_static.diff_cases(
        paths.input_file(args["path_a"], {".genkey"}),
        paths.input_file(args["path_b"], {".genkey"}),
    )


def opi_parse(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return genkey_static.parse_opi(paths.input_file(args["path"], {".opi"}))


def pipe_geometry(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    path = args.get("path") or workspace.active_path()
    if not path:
        raise ToolError(
            "No case path given and no active case set. Pick a case in the workspace or name one."
        )
    path = paths.input_file(path, {".genkey"})
    result = genkey_static.pipe_geometry(
        path,
        args["flowpath"],
        args.get("op", "list_pipes"),
    )
    paths.set_active_case(path)
    return result


def parametric_sweep(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    base = args.get("base") or workspace.active_path()
    if not base:
        raise ToolError(
            "No base case given and no active case set. Pick a case in the workspace or name one."
        )
    return sweep_execution.preview_sweep(
        paths.input_file(base, {".genkey"}),
        [args["sweep"]],
        args.get("strategy", "oat"),
        int(args.get("max_cases", 20)),
        runner.require_timeout_seconds(args.get("timeout_s", 3600)),
    )


def fluids_tab(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return fluids.inspect_tab(paths.input_file(args["path"], {".tab"}))


def fluids_mfl(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return fluids.inspect_mfl(paths.input_file(args["path"], {".mfl"}))


def fluids_consistency(
    args: ToolArgs, paths: PathBindings = DEFAULT_PATHS
) -> ToolResult:
    path = args.get("path") or workspace.active_path()
    if not path:
        raise ToolError(
            "No case path given and no active case set. Pick a case in the workspace or name one."
        )
    return fluids.consistency(paths.input_file(path, {".genkey"}))


def fluids_draft_preview(args: ToolArgs) -> ToolResult:
    """Render an .mfl draft without writing anything."""
    from .. import fluid_table

    try:
        label = fluid_table.validate_label(args.get("fluid_label"))
        model = fluid_table.validate_model(args.get("model"))
        names = fluid_table.databank_names()
        components = fluid_table.validate_composition(
            fluid_table.spell_components(args.get("components") or [], names),
            names,
        )
        temperatures = fluid_table.validate_grid(args.get("temperatures"), "temperature")
        pressures = fluid_table.validate_grid(args.get("pressures"), "pressure")
        temperature_unit = str(args.get("temperature_unit") or "")
        pressure_unit = str(args.get("pressure_unit") or "")
        mfl_rel = str(args.get("mfl_rel") or "")
        if not mfl_rel:
            raise fluid_table.FluidTableError("mfl_rel is required.")
        target = workspace.contained(mfl_rel)
        if target.suffix.casefold() != ".mfl":
            raise fluid_table.FluidTableError("Draft destination must end in .mfl.")
        tab_given = args.get("tab_rel")
        tab_target = (
            workspace.contained(str(tab_given)) if tab_given else target.with_suffix(".tab")
        )
        command = fluid_table.build_table_command(
            str(tab_target.resolve()), label, temperatures, temperature_unit,
            pressures, pressure_unit, hawater=bool(args.get("hawater", False)),
        )
        text = fluid_table.build_mfl_text(
            fluid_label=label, components=components, model=model,
            temperatures=temperatures, temperature_unit=temperature_unit,
            pressures=pressures, pressure_unit=pressure_unit,
            tab_abs_path=str(tab_target.resolve()),
            hawater=bool(args.get("hawater", False)),
        )
    except (fluid_table.FluidTableError, workspace.WorkspaceError) as exc:
        raise ToolError(str(exc)) from exc
    return {
        "mfl_rel": mfl_rel,
        "tab_abs": str(tab_target.resolve()),
        "table_command": command,
        "mfl_text": text,
        "writes_nothing": True,
    }


def fluids_pickup_tab(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    """Validate a produced .tab and check its label; read-only."""
    from .. import fluid_table

    raw = str(args.get("path") or "")
    if not raw:
        raise ToolError("A .tab or .mfl path is required.")
    resolved = paths.input_file(raw, {".tab", ".mfl"})
    tab_path = resolved
    if resolved.casefold().endswith(".mfl"):
        try:
            expected = fluid_table.expected_tab_for_mfl(resolved)
        except fluid_table.FluidTableError as exc:
            raise ToolError(str(exc)) from exc
        if expected is None:
            raise ToolError("The .mfl has no table Olga .tab path to pick up.")
        tab_path = expected
    try:
        return fluid_table.pickup_tab(tab_path, args.get("fluid_label"))
    except fluid_table.FluidTableError as exc:
        raise ToolError(str(exc)) from exc


def fluids_compare_tab(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    """Compare an owner Multiflash table with the app engine table; read-only."""
    from .. import tab_compare

    reference = str(args.get("reference_rel") or "")
    candidate = str(args.get("candidate_rel") or "")
    if not reference or not candidate:
        raise ToolError("Both reference_rel and candidate_rel are required.")
    try:
        report = tab_compare.compare_tables(
            paths.input_file(reference, {".tab"}),
            paths.input_file(candidate, {".tab"}),
        )
    except tab_compare.GridMismatchError as exc:
        raise ToolError(str(exc)) from exc
    return {**report, "writes_nothing": True}


def results_load(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return _result_tools.load(args, paths)


def results_inventory(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return _result_tools.inventory(args, paths)


def results_series(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return _result_tools.series(args, paths)


def results_profile(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return _result_tools.profile(args, paths)


def results_csv(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return _artifact_tools.csv_export(args, paths)


def results_plot(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return _artifact_tools.plot_export(args, paths)


def evaluate(args: ToolArgs) -> ToolResult:
    return evaluation_adapter.evaluate(args["criteria"])


def report_markdown(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return reports.markdown_report(
        paths.input_file(args["genkey"], {".genkey"}),
        paths.result_file(args["results"]) if args.get("results") else None,
        paths.result_file(args["ppl"]) if args.get("ppl") else None,
        args.get("criterion"),
        args.get("flowpath"),
        args.get("pipe"),
        args.get("title"),
        args.get("verdicts"),
        args.get("figures"),
    )


def report_figure(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return _artifact_tools.report_figure(args, paths)


def report_compare(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return reports.compare_cases(
        [paths.result_file(path) for path in args["files"]],
        args.get("labels"),
        args.get("variables"),
        args.get("branch"),
        args.get("timestep"),
    )


def diagnose_out(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return diagnostics.diagnose_out(paths.input_file(args["path"], {".out", ".log"}))


def monitor_snapshot(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    return diagnostics.monitor_snapshot(
        paths.input_file(args["path"], {".out", ".log"})
    )


def run_detect(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    source = args.get("source")
    return runner.detect_olga(paths.input_file(source, {".genkey"}) if source else None)


def run_preview(args: ToolArgs, paths: PathBindings = DEFAULT_PATHS) -> ToolResult:
    source = args.get("source") or workspace.active_path()
    if not source:
        raise ToolError(
            "No case source given and no active case set. Pick a case in the workspace or name one."
        )
    source = paths.input_file(source, {".genkey"})
    from .. import pvt_range

    refusals, range_warnings = pvt_range.check_genkey_source(source)
    if refusals:
        raise ToolRefusedError(refusals[0])
    result = runner.preview_run(
        source,
        runner.require_timeout_seconds(args.get("timeout_s", 3600)),
    )
    paths.set_active_case(source)
    if range_warnings:
        result = {**result, "pvt_range_warnings": range_warnings}
    return result


def run_status(args: ToolArgs) -> ToolResult:
    return runner.run_status(args["run_id"])


def sweep_status(args: ToolArgs) -> ToolResult:
    try:
        return sweep_execution.sweep_status(args["sweep_id"])
    except sweep_execution.UnknownSweepError as exc:
        raise ToolError(f"Unknown sweep id: {args['sweep_id']}") from exc
