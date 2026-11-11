"""Allowlisted agent tool facade.

The model sees only the schemas returned by :func:`tool_specs`. Execution
stays constrained to known adapters, side-effectful execution consumes a
human-minted approval, and every transcript result is byte-bounded.

Compatibility wrappers intentionally remain in this module: callers and tests
patch adapter modules through ``olga_companion.agent.tools`` and registered
handlers have historically reported this module as their owner.
"""

from __future__ import annotations

from typing import Any

from .. import (
    config,
    diagnostics,
    evaluation,
    fluids,
    genkey_static,
    reports,
    results,
    run_patrol,
    runner,
    sweep_execution,
    workspace,
)
from . import approvals
from . import case_transaction_tools as _case_transactions
from . import pipe_table_tools as _pipe_tables
from . import simulation_setup_adapter as _simulation_setup
from . import tool_read_tools as _read
from . import approval_display as _approval_display
from . import tool_side_effects as _side_effects
from . import tool_validation as _validation
from .tool_schemas import Tool, build_tools, schema

MAX_RESULT_BYTES = _validation.MAX_RESULT_BYTES
CASE_ARG_KEY = _validation.CASE_ARG_KEY
ToolError = _validation.ToolError
ToolFailedError = _validation.ToolFailedError
ToolRefusedError = _validation.ToolRefusedError
Tool.__module__ = __name__
ToolError.__module__ = __name__


# Tools that exist only while OLGA_COMPANION_NATIVE_TAB=1.
_NATIVE_TAB_TOOLS = frozenset({"fluids_generate_tab"})


class ToolPreDispatchError(ToolError):
    """The handler was never entered, so releasing an approval claim is safe."""


_ADAPTER_MONKEYPATCH_SEAMS = (
    diagnostics,
    evaluation,
    fluids,
    genkey_static,
    reports,
    results,
    runner,
    sweep_execution,
    workspace,
    approvals,
)


def apply_active_default(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Fill a case tool's omitted path before approval payload creation."""
    return _validation.apply_active_default(name, args, CASE_ARG_KEY)


def _set_active_case(path: str | None) -> str | None:
    return _validation.set_active_case(path)


def _input_file(value: str, suffixes: set[str]) -> str:
    return _validation.input_file(value, suffixes)


def _result_file(value: str) -> str:
    return _validation.result_file(value)


def _path_bindings() -> _validation.PathBindings:
    return _validation.PathBindings(_input_file, _result_file, _set_active_case)


def _truncate_value(value: Any, cap: int) -> Any:
    return _validation.truncate_value(value, cap)


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    return _validation.cap(payload, MAX_RESULT_BYTES, _truncate_value)


def _schema(props: dict[str, str], required: list[str]) -> dict[str, Any]:
    return schema(props, required)


def _t_genkey_create(args: dict[str, Any]) -> dict[str, Any]:
    return _read.genkey_create(args)


def _t_case_spec_validate(args: dict[str, Any]) -> dict[str, Any]:
    return _read.case_spec_validate(args)


def _t_case_spec_compile(args: dict[str, Any]) -> dict[str, Any]:
    return _read.case_spec_compile(args, _path_bindings())


def _t_case_edit_plan(args: dict[str, Any]) -> dict[str, Any]:
    return _case_transactions.edit_plan(args, _path_bindings())


def _t_pipe_table_import(args: dict[str, Any]) -> dict[str, Any]:
    return _pipe_tables.import_table(args, _path_bindings())


def _t_case_draft_review(args: dict[str, Any]) -> dict[str, Any]:
    return _pipe_tables.review(args)


def _t_case_draft_edit(args: dict[str, Any]) -> dict[str, Any]:
    return _pipe_tables.edit(args)


def _t_case_publish(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.case_publish(args)


def _t_action_plan(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.action_plan(args)


def _t_simulation_setup(args: dict[str, Any]) -> dict[str, Any]:
    return _simulation_setup.execute(args)


def _t_run_patrol(args: dict[str, Any]) -> dict[str, Any]:
    return run_patrol.patrol_run(
        str(args["run_id"]),
        deadline_s=float(args["deadline_s"]),
        max_polls=int(args["max_polls"]),
        backoff_s=float(args["backoff_s"]),
    )


def _t_genkey_review(args: dict[str, Any]) -> dict[str, Any]:
    return _read.genkey_review(args, _path_bindings())


def _t_genkey_topology(args: dict[str, Any]) -> dict[str, Any]:
    return _read.genkey_topology(args, _path_bindings())


def _t_genkey_modify(args: dict[str, Any]) -> dict[str, Any]:
    return _read.genkey_modify(args, _path_bindings())


def _t_genkey_diff(args: dict[str, Any]) -> dict[str, Any]:
    return _read.genkey_diff(args, _path_bindings())


def _t_genkey_save(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.genkey_save(args, approval_payload)


def _t_opi_parse(args: dict[str, Any]) -> dict[str, Any]:
    return _read.opi_parse(args, _path_bindings())


def _t_pipe_geometry(args: dict[str, Any]) -> dict[str, Any]:
    return _read.pipe_geometry(args, _path_bindings())


def _t_parametric_sweep(args: dict[str, Any]) -> dict[str, Any]:
    return _read.parametric_sweep(args, _path_bindings())


def _t_sweep_cancel(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.sweep_cancel(args, approval_payload)


def _t_sweep_status(args: dict[str, Any]) -> dict[str, Any]:
    return _read.sweep_status(args)


def _t_fluids_tab(args: dict[str, Any]) -> dict[str, Any]:
    return _read.fluids_tab(args, _path_bindings())


def _t_fluids_mfl(args: dict[str, Any]) -> dict[str, Any]:
    return _read.fluids_mfl(args, _path_bindings())


def _t_fluids_consistency(args: dict[str, Any]) -> dict[str, Any]:
    return _read.fluids_consistency(args, _path_bindings())


def _t_fluids_draft_preview(args: dict[str, Any]) -> dict[str, Any]:
    return _read.fluids_draft_preview(args)


def _t_fluids_pickup_tab(args: dict[str, Any]) -> dict[str, Any]:
    return _read.fluids_pickup_tab(args, _path_bindings())


def _t_fluids_compare_tab(args: dict[str, Any]) -> dict[str, Any]:
    return _read.fluids_compare_tab(args, _path_bindings())


def _t_fluids_draft_mfl(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.fluids_draft_mfl(args, approval_payload)


def _t_fluids_generate_tab(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.fluids_generate_tab(args, approval_payload)


def _t_fluids_starter_tab(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.fluids_starter_tab(args, approval_payload)


def _t_multiflash_open(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.multiflash_open(args, approval_payload)


def _t_results_load(args: dict[str, Any]) -> dict[str, Any]:
    return _read.results_load(args, _path_bindings())


def _t_results_inventory(args: dict[str, Any]) -> dict[str, Any]:
    return _read.results_inventory(args, _path_bindings())


def _t_results_series(args: dict[str, Any]) -> dict[str, Any]:
    return _read.results_series(args, _path_bindings())


def _t_results_profile(args: dict[str, Any]) -> dict[str, Any]:
    return _read.results_profile(args, _path_bindings())


def _t_results_csv(args: dict[str, Any]) -> dict[str, Any]:
    return _read.results_csv(args, _path_bindings())


def _t_results_plot(args: dict[str, Any]) -> dict[str, Any]:
    return _read.results_plot(args, _path_bindings())


def _t_evaluate(args: dict[str, Any]) -> dict[str, Any]:
    return _read.evaluate(args)


def _t_report_markdown(args: dict[str, Any]) -> dict[str, Any]:
    return _read.report_markdown(args, _path_bindings())


def _t_report_figure(args: dict[str, Any]) -> dict[str, Any]:
    return _read.report_figure(args, _path_bindings())


def _t_report_compare(args: dict[str, Any]) -> dict[str, Any]:
    return _read.report_compare(args, _path_bindings())


def _t_olga_glossary(args: dict[str, Any]) -> dict[str, Any]:
    from ..glossary import lookup

    return lookup(args.get("term"))


def _t_diagnose_out(args: dict[str, Any]) -> dict[str, Any]:
    return _read.diagnose_out(args, _path_bindings())


def _t_monitor_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    return _read.monitor_snapshot(args, _path_bindings())


def _t_run_detect(args: dict[str, Any]) -> dict[str, Any]:
    return _read.run_detect(args, _path_bindings())


def _t_run_preview(args: dict[str, Any]) -> dict[str, Any]:
    return _read.run_preview(args, _path_bindings())


def _t_run_cancel(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.run_cancel(args, approval_payload)


def _t_run_status(args: dict[str, Any]) -> dict[str, Any]:
    return _read.run_status(args)


def approval_payload(action_kind: str, args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.approval_payload(action_kind, args, _path_bindings())


def approval_display(
    action_kind: str, args: dict[str, Any], locale: str = "ko"
) -> dict[str, Any]:
    return _approval_display.build(action_kind, args, _path_bindings(), locale=locale)


def _t_run_execute(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.run_execute(args, _path_bindings(), approval_payload)


def _t_sweep_execute(args: dict[str, Any]) -> dict[str, Any]:
    return _side_effects.sweep_execute(args, approval_payload)


_HANDLERS = {
    handler.__name__: handler
    for handler in (
        _t_genkey_create,
        _t_case_spec_validate,
        _t_case_spec_compile,
        _t_case_edit_plan,
        _t_pipe_table_import,
        _t_case_draft_review,
        _t_case_draft_edit,
        _t_case_publish,
        _t_action_plan,
        _t_simulation_setup,
        _t_run_patrol,
        _t_genkey_review,
        _t_genkey_topology,
        _t_genkey_modify,
        _t_genkey_diff,
        _t_genkey_save,
        _t_opi_parse,
        _t_pipe_geometry,
        _t_parametric_sweep,
        _t_sweep_execute,
        _t_sweep_cancel,
        _t_sweep_status,
        _t_fluids_tab,
        _t_fluids_mfl,
        _t_fluids_consistency,
        _t_fluids_draft_preview,
        _t_fluids_draft_mfl,
        _t_fluids_generate_tab,
        _t_fluids_starter_tab,
        _t_fluids_pickup_tab,
        _t_fluids_compare_tab,
        _t_multiflash_open,
        _t_results_load,
        _t_results_inventory,
        _t_results_series,
        _t_results_profile,
        _t_results_csv,
        _t_results_plot,
        _t_evaluate,
        _t_report_markdown,
        _t_report_figure,
        _t_report_compare,
        _t_olga_glossary,
        _t_diagnose_out,
        _t_monitor_snapshot,
        _t_run_detect,
        _t_run_preview,
        _t_run_execute,
        _t_run_cancel,
        _t_run_status,
    )
}
TOOLS: dict[str, Tool] = build_tools(_HANDLERS)


def tool_specs() -> list[dict[str, Any]]:
    """Return model capabilities without server-only approval credentials."""
    specs = []
    for tool in TOOLS.values():
        parameters = tool.parameters
        if tool.side_effect:
            parameters = {
                **parameters,
                "properties": {
                    name: item_schema
                    for name, item_schema in parameters.get("properties", {}).items()
                    if name not in {"approval_token", "idempotency_key"}
                },
                "required": [
                    name
                    for name in parameters.get("required", [])
                    if name not in {"approval_token", "idempotency_key"}
                ],
            }
        specs.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": parameters,
            }
        )
    return specs


def dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute an allowlisted tool by name and cap its result."""
    tool = TOOLS.get(name)
    if tool is None or (name in _NATIVE_TAB_TOOLS and not config.native_tab_enabled()):
        raise ToolPreDispatchError(f"Tool is not allowlisted: {name!r}")
    if not isinstance(args, dict):
        raise ToolPreDispatchError("Tool arguments must be an object.")
    try:
        _validation.validate_tool_arguments(name, args, tool.parameters)
    except ToolError as exc:
        raise ToolPreDispatchError(str(exc)) from exc
    try:
        result = tool.handler(args)
    except (workspace.StaleWorkspaceContextError, ToolFailedError):
        raise
    except (
        genkey_static.OlgaInputError,
        workspace.WorkspaceError,
        ToolError,
        approvals.ApprovalError,
    ) as exc:
        raise ToolError(str(exc)) from exc
    except KeyError as exc:
        raise ToolError(f"Missing required argument: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ToolError(f"Invalid arguments for {name!r}: {exc}") from exc
    _validation.validate_tool_result(name, result, tool.response_schema)
    return _cap(result)
