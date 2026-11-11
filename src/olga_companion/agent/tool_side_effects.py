"""Approval-bound execution handlers for the agent tool belt."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import os

from .. import config, genkey_static, pvt_range, runner, sweep_execution, workspace
from . import approvals, case_publish_adapter, plan_model
from .case_transaction_schemas import DESTINATION_RULE
from .tool_validation import DEFAULT_PATH_BINDINGS, PathBindings, ToolError, ToolFailedError, ToolRefusedError

SIDE_EFFECT_TOOL_METADATA: Final = {
    "action_plan": (
        "Ask for ONE approval card that lists a short, ordered sequence of at most "
        f"{plan_model.MAX_STEPS} steps: fluids_draft_mfl, case_publish and run_execute, each with the "
        "exact args that tool takes. A run_execute step that follows a case_publish step may set "
        "source_from_step to that step's number and omit source and selection_id: the run then starts "
        "only if the published case previews and validates cleanly at that moment. A plan holds at "
        "most one run_execute; one without source_from_step must give its own source and selection_id. "
        "After one human "
        "approval the steps run in order, each is re-checked first, the sequence stops at the first "
        "failure, and nothing can be added to it afterwards. run_cancel, sweep_execute, sweep_cancel "
        "and genkey_save never join a plan.",
        {},
        [],
    ),
    "case_publish": (
        "Publish exactly one reviewed case transaction to its approved destination. " + DESTINATION_RULE,
        {},
        [],
    ),
    "fluids_draft_mfl": (
        "Write a new Multiflash .mfl draft from the user's own composition after explicit human approval. Never overwrites; the destination must not exist.",
        {},
        [],
    ),
    "fluids_starter_tab": (
        "Copy the generic air-water PVT table (.tab) that ships with the app into the workspace as a "
        "new file after explicit human approval. It is a generic table (CPA, 0-80 C, 0.5-20 bar, "
        "fluid label AIR_WATER), not made for the user's case. The file must not exist yet; it is "
        "never overwritten.",
        {},
        [],
    ),
    "fluids_generate_tab": (
        "Compute a PVT table (.tab) inside the app with the independent engine after explicit human "
        "approval. It is an independent table, not Multiflash-identical, and it is never qualified for "
        "OLGA use by this app. Use only the user's own composition, model and grid. The file must not "
        "exist yet; it is never overwritten. A grid holds at most {nodes} nodes (temperatures times "
        "pressures). The result gives the validator summary and the number of nodes that had to be "
        "filled (a phase absent at that state). When the Multiflash databank and sample template "
        "are available it also writes a companion .mfl for the same composition; that draft's table "
        "command targets <name>_mf.tab, so Multiflash does not overwrite this table. If they are "
        "unavailable the table is still written and the result says the draft was skipped.",
        {},
        [],
    ),
    "multiflash_open": (
        "Open the drafted .mfl in the bundled Multiflash GUI after explicit human approval. The user runs the table command there; the app never drives Multiflash itself.",
        {},
        [],
    ),
    "genkey_save": (
        "Publish a generated GENKEY into the workspace after explicit human approval.",
        {
            "save_rel": "string",
            "topology": "string",
            "endtime_s": "integer",
            "pvtfile": "string",
            "approval_token": "string",
            "idempotency_key": "string",
        },
        ["save_rel", "topology", "approval_token", "idempotency_key"],
    ),
    "sweep_execute": (
        "Request execution of exactly a previously previewed parametric sweep plan. Requires its plan_id and explicit human approval.",
        {
            "sweep_id": "string",
            "plan_id": "string",
            "approval_token": "string",
            "idempotency_key": "string",
        },
        ["sweep_id", "plan_id", "approval_token", "idempotency_key"],
    ),
    "run_execute": (
        "Request execution of exactly the runtime selection returned by run_preview in the sandbox. Requires its selection_id and explicit human approval. Omit source to use the active case.",
        {
            "source": "string",
            "timeout_s": "integer",
            "selection_id": "string",
            "approval_token": "string",
            "idempotency_key": "string",
        },
        ["selection_id", "approval_token", "idempotency_key"],
    ),
    "run_cancel": (
        "Cancel one running OLGA process after explicit human approval.",
        {"run_id": "string", "approval_token": "string", "idempotency_key": "string"},
        ["run_id", "approval_token", "idempotency_key"],
    ),
    "sweep_cancel": (
        "Cancel every running child of one sweep after explicit human approval.",
        {"sweep_id": "string", "approval_token": "string", "idempotency_key": "string"},
        ["sweep_id", "approval_token", "idempotency_key"],
    ),
}


def approval_payload(
    action_kind: str,
    args: dict[str, Any],
    paths: PathBindings = DEFAULT_PATH_BINDINGS,
) -> dict[str, Any]:
    """Build the canonical payload bound to a human approval token."""
    if action_kind == plan_model.PLAN_KIND:
        return _plan_payload(args, paths)
    if action_kind == "case_publish":
        return case_publish_adapter.approval_payload(args)
    if action_kind == "fluids_draft_mfl":
        return _fluid_draft_payload(args)
    if action_kind == "fluids_generate_tab":
        return _generate_tab_payload(args)
    if action_kind == "fluids_starter_tab":
        return _starter_tab_payload(args)
    if action_kind == "multiflash_open":
        return _multiflash_open_payload(args, paths)
    if action_kind == "run_execute":
        source = args.get("source") or workspace.active_path()
        selection_id = str(args.get("selection_id") or "")
        if not source or not selection_id:
            raise ToolError("The pending run approval is incomplete.")
        return {
            "source": paths.input_file(source, {".genkey"}),
            "timeout_s": runner.require_timeout_seconds(args.get("timeout_s", 3600)),
            "selection_id": selection_id,
        }
    if action_kind == "genkey_save":
        save_rel = str(args.get("save_rel") or "")
        topology = str(args.get("topology") or "")
        if not save_rel or not topology:
            raise ToolError("The pending GENKEY publish approval is incomplete.")
        try:
            target = workspace.contained(save_rel)
        except workspace.WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        if target.suffix.casefold() != ".genkey":
            raise ToolError("GENKEY publish destination must end in .genkey.")
        return {
            "save_rel": str(target.relative_to(workspace.context_identity()[0])),
            "topology": topology,
            "endtime_s": int(args.get("endtime_s", 3600)),
            "pvtfile": str(args.get("pvtfile", "./fluid.tab")),
        }
    if action_kind == "run_cancel":
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ToolError("The pending run cancellation approval is incomplete.")
        return {"run_id": run_id}
    if action_kind == "sweep_cancel":
        sweep_id = str(args.get("sweep_id") or "")
        if not sweep_id:
            raise ToolError("The pending sweep cancellation approval is incomplete.")
        return {"sweep_id": sweep_id}
    if action_kind == "sweep_execute":
        sweep_id = str(args.get("sweep_id") or "")
        plan_id = str(args.get("plan_id") or "")
        if not sweep_id or not plan_id:
            raise ToolError("The pending sweep approval is incomplete.")
        return sweep_execution.approval_payload(sweep_id, plan_id)
    raise ToolError(f"Unsupported pending approval action: {action_kind}")


def _plan_payload(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    """Canonicalize a plan: exact steps are pinned now, a bound run step stays a rule."""
    from .tool_schema_catalog import parameter_schema
    from .tool_validation import validate_tool_arguments

    try:
        steps = plan_model.canonical_steps(args.get("steps"))
    except plan_model.PlanError as exc:
        raise ToolError(str(exc)) from exc
    rows: list[dict[str, Any]] = []
    # Tables that an earlier step of this plan creates: the only ones a later publish may still lack.
    planned: dict[Path, str] = {}
    for number, step in enumerate(steps, start=1):
        kind = step["kind"]
        if kind in plan_model.unavailable_kinds():
            raise ToolError(f"Step {number}: {kind} is not available in this build.")
        try:
            validate_tool_arguments(kind, step["args"], parameter_schema(kind))
            if kind == "case_publish":
                rows.append({
                    "kind": kind,
                    "payload": case_publish_adapter.approval_payload(step["args"], planned_tables=planned),
                    "bind": None,
                })
            elif "source_from_step" in step:
                timeout = runner.require_timeout_seconds(step["args"].get("timeout_s", 3600))
                rows.append({
                    "kind": kind,
                    "payload": None,
                    "bind": {"source_from_step": step["source_from_step"]},
                    "timeout_s": timeout,
                })
            else:
                pinned = approval_payload(kind, step["args"], paths)
                if kind == "fluids_generate_tab":
                    planned[workspace.contained(pinned["tab_rel"]).resolve()] = pinned["fluid_label"]
                rows.append({"kind": kind, "payload": pinned, "bind": None})
        except ToolError as exc:
            raise ToolError(f"Step {number} ({kind}): {exc}") from exc
    return {"steps": rows}


def action_plan(_args: dict[str, Any]) -> dict[str, Any]:
    """A plan has no direct handler: only the approval route runs its steps."""
    raise ToolError("action_plan runs only from the approval route after a human approves it.")


def _fluid_draft_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize a draft request; raises ToolError on any invented data."""
    from .. import fluid_table, workspace

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
        temperature_unit = fluid_table.canonical_temperature_unit(
            args.get("temperature_unit")
        )
        pressure_unit = fluid_table.canonical_pressure_unit(
            args.get("pressure_unit")
        )
    except fluid_table.FluidTableError as exc:
        raise ToolError(str(exc)) from exc
    mfl_rel = str(args.get("mfl_rel") or "")
    if not mfl_rel:
        raise ToolError("mfl_rel is required: a workspace-relative .mfl destination.")
    try:
        root, _ = workspace.context_identity()
        target = workspace.contained(mfl_rel)
    except workspace.WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    if target.suffix.casefold() != ".mfl":
        raise ToolError("Draft destination must end in .mfl.")
    tab_given = args.get("tab_rel")
    try:
        tab_target = workspace.contained(str(tab_given)) if tab_given else target.with_suffix(".tab")
    except workspace.WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    if tab_target.suffix.casefold() != ".tab":
        raise ToolError("Table destination must end in .tab.")
    return {
        "mfl_rel": str(target.relative_to(root)),
        "tab_rel": str(tab_target.relative_to(root)),
        "tab_abs": str(tab_target.resolve()),
        "fluid_label": label,
        "components": components,
        "model": model,
        "temperatures": temperatures,
        "temperature_unit": temperature_unit,
        "pressures": pressures,
        "pressure_unit": pressure_unit,
        "hawater": bool(args.get("hawater", False)),
    }


def _generate_tab_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize a table request; every refusal here happens before any card exists."""
    if not config.native_tab_enabled():
        raise ToolError("fluids_generate_tab is not available in this build.")
    from .. import fluid_table, native_tab

    try:
        request = native_tab.canonical_request(args)
        tab_rel = str(args.get("tab_rel") or "")
        if not tab_rel:
            raise ToolError("tab_rel is required: a new workspace-relative .tab destination.")
        root, _ = workspace.context_identity()
        target = workspace.contained(tab_rel)
    except fluid_table.FluidTableError as exc:
        raise ToolError(str(exc)) from exc
    except workspace.WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    if target.suffix.casefold() != ".tab":
        raise ToolError("Table destination must end in .tab.")
    if not target.parent.is_dir():
        raise ToolError("The selected table folder does not exist.")
    mfl_target = target.with_suffix(".mfl")
    for existing in (*native_tab.table_paths(target), mfl_target):
        if os.path.lexists(existing):
            raise ToolError(
                f"{existing.name} already exists; choose a new table name. Nothing is ever overwritten."
            )
    return {
        **request,
        "tab_rel": str(target.relative_to(root)),
        "mfl_rel": str(mfl_target.relative_to(root)),
    }


def _starter_tab_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize a starter-table request; every refusal here happens before any card exists."""
    from .. import starter_fluids

    tab_rel = str(args.get("tab_rel") or "")
    if not tab_rel:
        raise ToolError("tab_rel is required: a new workspace-relative .tab destination.")
    try:
        root, _ = workspace.context_identity()
        target = workspace.contained(tab_rel)
    except workspace.WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    if target.suffix.casefold() != ".tab":
        raise ToolError("Table destination must end in .tab.")
    if not target.parent.is_dir():
        raise ToolError("The selected table folder does not exist.")
    if os.path.lexists(target):
        raise ToolError(f"{target.name} already exists; choose a new table name. Nothing is ever overwritten.")
    if not starter_fluids.bundled_table().is_file():
        raise ToolError("The generic air-water table is not included in this build.")
    return {"tab_rel": str(target.relative_to(root)), "fluid_label": starter_fluids.LABEL}


def _multiflash_open_payload(
    args: dict[str, Any],
    paths: PathBindings,
) -> dict[str, Any]:
    mfl_path = args.get("mfl_path")
    if mfl_path:
        return {"mfl_path": paths.input_file(str(mfl_path), {".mfl"})}
    return {"mfl_path": None}


ApprovalPayloadBuilder = Callable[[str, dict[str, Any]], dict[str, Any]]


def run_execute(
    args: dict[str, Any],
    paths: PathBindings = DEFAULT_PATH_BINDINGS,
    payload_builder: ApprovalPayloadBuilder = approval_payload,
) -> dict[str, Any]:
    """Execute exactly the previewed run after consuming human approval."""
    token = args.get("approval_token")
    if not token:
        raise ToolError(
            "run_execute requires an approval_token minted by the human clicking "
            "Approve on the command preview. Call run_preview and wait for approval."
        )
    source = args.get("source") or workspace.active_path()
    if not source:
        raise ToolError(
            "No case source given and no active case set. Pick a case in the workspace or name one."
        )
    source = paths.input_file(source, {".genkey"})
    timeout_s = runner.require_timeout_seconds(args.get("timeout_s", 3600))
    selection_id = str(args.get("selection_id") or "")
    if not selection_id:
        raise ToolError(
            "run_execute requires the selection_id returned by run_preview."
        )
    try:
        approvals.consume(
            token,
            "run_execute",
            payload_builder("run_execute", args),
            context_generation=workspace.context_generation(),
        )
    except approvals.ApprovalError as exc:
        raise ToolError(str(exc)) from exc
    refusals, range_warnings = pvt_range.check_genkey_source(source)
    if refusals:
        # A definite pre-launch failure: nothing started, so the run is refused.
        raise ToolRefusedError(refusals[0])
    try:
        result = runner.execute_run(
            source,
            approved=True,
            timeout_s=timeout_s,
            selection_id=selection_id,
        )
    except genkey_static.OlgaInputError as exc:
        # Every input error execute_run raises comes before the process starts.
        raise ToolRefusedError(str(exc)) from exc
    paths.set_active_case(source)
    if range_warnings:
        result = {**result, "pvt_range_warnings": range_warnings}
    return result


def sweep_execute(
    args: dict[str, Any],
    payload_builder: ApprovalPayloadBuilder = approval_payload,
) -> dict[str, Any]:
    """Execute exactly the previewed sweep after consuming human approval."""
    token = args.get("approval_token")
    if not token:
        raise ToolError(
            "sweep_execute requires an approval_token minted by the human clicking "
            "Approve on the generated sweep matrix. Call parametric_sweep and wait for approval."
        )
    sweep_id = str(args.get("sweep_id") or "")
    if not sweep_id:
        raise ToolError("sweep_id is required. Call parametric_sweep first.")
    plan_id = str(args.get("plan_id") or "")
    if not plan_id:
        raise ToolError(
            "sweep_execute requires the plan_id returned by parametric_sweep."
        )
    try:
        approvals.consume(
            token,
            "sweep_execute",
            payload_builder("sweep_execute", args),
            context_generation=workspace.context_generation(),
        )
        return sweep_execution.execute_sweep(
            sweep_id,
            approved=True,
            plan_id=plan_id,
        )
    except approvals.ApprovalError as exc:
        raise ToolError(str(exc)) from exc
    except sweep_execution.UnknownSweepError as exc:
        raise ToolError(f"Unknown sweep id: {sweep_id}") from exc


def _consume(
    action_kind: str,
    args: dict[str, Any],
    payload_builder: ApprovalPayloadBuilder,
) -> None:
    token = args.get("approval_token")
    if not token or not args.get("idempotency_key"):
        raise ToolError(
            f"{action_kind} requires a server-issued approval capability and idempotency key."
        )
    try:
        approvals.consume(
            str(token),
            action_kind,
            payload_builder(action_kind, args),
            context_generation=workspace.context_generation(),
        )
    except approvals.ApprovalError as exc:
        raise ToolError(str(exc)) from exc


def genkey_save(args: dict[str, Any], payload_builder: ApprovalPayloadBuilder) -> dict[str, Any]:
    _consume("genkey_save", args, payload_builder)
    target = payload_builder("genkey_save", args)
    return genkey_static.create_and_save(
        str(workspace.contained(target["save_rel"])),
        target["topology"],
        target["endtime_s"],
        target["pvtfile"],
    )


def fluids_draft_mfl(args: dict[str, Any], payload_builder: ApprovalPayloadBuilder) -> dict[str, Any]:
    """Write the approved .mfl draft exactly once, never overwriting."""
    from .. import fluid_table

    _consume("fluids_draft_mfl", args, payload_builder)
    target = payload_builder("fluids_draft_mfl", args)
    text = fluid_table.build_mfl_text(
        fluid_label=target["fluid_label"],
        components=target["components"],
        model=target["model"],
        temperatures=target["temperatures"],
        temperature_unit=target["temperature_unit"],
        pressures=target["pressures"],
        pressure_unit=target["pressure_unit"],
        tab_abs_path=target["tab_abs"],
        hawater=target["hawater"],
    )
    try:
        written = fluid_table.write_draft_mfl(
            str(workspace.contained(target["mfl_rel"])), text
        )
    except fluid_table.FluidTableError as exc:
        raise ToolError(str(exc)) from exc
    return {
        **written,
        # Absolute paths are redacted for the model and the card; these names stay readable.
        "mfl_rel": target["mfl_rel"],
        "tab_rel": target["tab_rel"],
        "tab_abs": target["tab_abs"],
        "table_command": fluid_table.build_table_command(
            target["tab_abs"], target["fluid_label"], target["temperatures"],
            target["temperature_unit"], target["pressures"], target["pressure_unit"],
            hawater=target["hawater"],
        ),
    }


_VALIDATOR_SAMPLE = 5


def _validator_summary(check: dict[str, Any]) -> dict[str, Any]:
    errors, warnings = check.get("errors") or [], check.get("warnings") or []

    def text(item: object) -> str:
        message = item.get("message") if isinstance(item, dict) else item
        return " ".join(str(message).split())[:160]

    return {
        "valid": bool(check.get("valid")),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": [text(item) for item in errors[:_VALIDATOR_SAMPLE]],
        "warnings": [text(item) for item in warnings[:_VALIDATOR_SAMPLE]],
    }


def _companion_mfl(request: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Write ``<name>.mfl`` beside the table. A missing databank or template skips it."""
    from .. import fluid_table, native_tab

    mfl_path = destination.with_suffix(".mfl")
    try:
        model = native_tab.MFL_MODEL[str(request["model"])]
        names = fluid_table.databank_names()
        text = fluid_table.build_mfl_text(
            fluid_label=request["fluid_label"],
            components=fluid_table.spell_components(request["components"], names),
            model=model,
            temperatures=request["temperatures"],
            temperature_unit=request["temperature_unit"],
            pressures=request["pressures"],
            pressure_unit=request["pressure_unit"],
            tab_abs_path=str(destination.with_name(f"{destination.stem}_mf.tab").resolve()),
            databank_names=names,
        )
        fluid_table.write_draft_mfl(str(mfl_path), text)
    except (fluid_table.FluidTableError, OSError, KeyError) as exc:
        return {"mfl_rel": None, "mfl_note": f"Companion .mfl skipped: {exc}"}
    root, _generation = workspace.context_identity()
    return {"mfl_rel": str(mfl_path.relative_to(root)), "mfl_note": None}


def fluids_generate_tab(args: dict[str, Any], payload_builder: ApprovalPayloadBuilder) -> dict[str, Any]:
    """Compute and write the approved table once, then run the validator on it."""
    from .. import fluid_table, native_tab

    try:
        _consume("fluids_generate_tab", args, payload_builder)
        request = payload_builder("fluids_generate_tab", args)
        destination = workspace.contained(request["tab_rel"])
    except (ToolError, workspace.WorkspaceError) as exc:
        # Every check up to here comes before the engine runs, so nothing was written.
        raise ToolRefusedError(str(exc)) from exc
    try:
        written = native_tab.generate(request, destination)
    except fluid_table.FluidTableError as exc:
        # The engine writes nothing when it refuses, so the step is safely a refusal.
        raise ToolRefusedError(str(exc)) from exc
    companion = _companion_mfl(request, destination)
    check = _validator_summary(fluid_table.pickup_tab(str(destination), request["fluid_label"]))
    if not check["valid"]:
        detail = "; ".join(check["errors"][:3]) or "no detail"
        # The file is already on disk, so this is a known failure after a write, not a refusal.
        raise ToolFailedError(
            f"The generated table {destination.name} was kept for inspection; do not link it. "
            f"It did not pass the validator ({check['error_count']} error(s): {detail})."
        )
    return {
        "ok": True,
        "tab_rel": request["tab_rel"],
        "fill_report_rel": str(Path(request["tab_rel"]).with_name(written["fill_report"].name)),
        "declared_label": request["fluid_label"],
        "model": request["model"],
        "node_count": written["node_count"],
        "filled_node_count": written["filled_node_count"],
        "validator": check,
        "table_kind": native_tab.TABLE_KIND,
        **companion,
        "next_step": (
            "Link the table through case_edit_plan and case_publish, or inside an action_plan "
            "(case_edit_plan pending_table) so one approval covers the table, the saved case and the run."
        ),
    }


def fluids_starter_tab(args: dict[str, Any], payload_builder: ApprovalPayloadBuilder) -> dict[str, Any]:
    """Copy the bundled air-water table to the approved new path, never overwriting."""
    from .. import fluid_table, starter_fluids

    try:
        _consume("fluids_starter_tab", args, payload_builder)
        request = payload_builder("fluids_starter_tab", args)
        destination = workspace.contained(request["tab_rel"])
    except (ToolError, workspace.WorkspaceError) as exc:
        # Every check up to here comes before the copy, so nothing was written.
        raise ToolRefusedError(str(exc)) from exc
    source = starter_fluids.bundled_table()
    check = _validator_summary(fluid_table.pickup_tab(str(source), starter_fluids.LABEL))
    if not check["valid"]:
        detail = "; ".join(check["errors"][:3]) or "no detail"
        raise ToolRefusedError(f"The bundled air-water table did not pass the validator: {detail}")
    try:
        with open(destination, "xb") as stream:
            stream.write(source.read_bytes())
    except FileExistsError as exc:
        raise ToolRefusedError(
            f"{destination.name} already exists; choose a new table name. Nothing is ever overwritten."
        ) from exc
    return {
        "ok": True,
        "tab_rel": request["tab_rel"],
        "fluid_label": starter_fluids.LABEL,
        "model": starter_fluids.MODEL,
        "table_kind": starter_fluids.KIND_EN,
        "validator": check,
        "next_step": (
            "Link the table through case_edit_plan and case_publish with this fluid label; the "
            "table's own composition is fixed and is used as it is."
        ),
    }


def multiflash_open(args: dict[str, Any], payload_builder: ApprovalPayloadBuilder) -> dict[str, Any]:
    """Launch the bundled Multiflash GUI exactly once per human approval."""
    from .. import fluid_table

    _consume("multiflash_open", args, payload_builder)
    target = payload_builder("multiflash_open", args)
    discovery = fluid_table.find_multiflash()
    if not discovery["found"]:
        raise ToolError(discovery["message"])
    try:
        return fluid_table.launch_multiflash(discovery["exe"], target["mfl_path"])
    except fluid_table.FluidTableError as exc:
        raise ToolError(str(exc)) from exc


def case_publish(args: dict[str, Any]) -> dict[str, Any]:
    """Publish an exact reviewed transaction using server-owned approval state."""
    return case_publish_adapter.execute(args)


def run_cancel(args: dict[str, Any], payload_builder: ApprovalPayloadBuilder) -> dict[str, Any]:
    _consume("run_cancel", args, payload_builder)
    return runner.cancel_run(str(args["run_id"]))


def sweep_cancel(args: dict[str, Any], payload_builder: ApprovalPayloadBuilder) -> dict[str, Any]:
    _consume("sweep_cancel", args, payload_builder)
    try:
        return sweep_execution.cancel_sweep(str(args["sweep_id"]))
    except sweep_execution.UnknownSweepError as exc:
        raise ToolError(f"Unknown sweep id: {args['sweep_id']}") from exc
