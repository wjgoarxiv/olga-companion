"""Server-reviewed, display-only facts for human approval cards."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Any

from .. import case_spec_recovery, case_transactions, genkey_static, pvt_range, runner, sweep_selection, workspace
from ..case_spec import CaseSpec
from ..case_spec_recovery import UnsupportedSourceError
from ..case_spec_types import ClosedNode, JunctionNode, SinkNode, SourceNode
from ..case_transaction_store import TransactionStoreError
from . import plan_model, tool_side_effects
from .tool_validation import DEFAULT_PATH_BINDINGS, PathBindings, ToolError

Previewer = Callable[[str, int], dict[str, Any]]
file_sha256 = genkey_static.file_sha256


def _executable_name(value: object) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return PureWindowsPath(raw).name if "\\" in raw else Path(raw).name


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def _row(group: str, name: str, value: object, unit: str) -> dict[str, str]:
    return {"group": group, "name": name, "value": _text(value), "unit": unit}


def _point(point: tuple[float, float, float]) -> str:
    return ", ".join(_text(axis) for axis in point)


def _labels(locale: str) -> Callable[[str, str], str]:
    """Pick the ko or en half of every per-row label pair.

    Labels travel with their row as plain (ko, en) pairs, so a mistyped word
    can only render wrong text — never raise KeyError. Anything but en stays
    Korean.
    """
    use_en = locale == "en"

    def text(ko: str, en: str) -> str:
        return en if use_en else ko

    return text


def reviewed_inputs(spec: CaseSpec, locale: str = "ko") -> list[dict[str, str]]:
    """User-facing numbers from a normalized CaseSpec, in card group order.

    Only the fixed group/field labels are localized; case-file labels, OLGA
    keywords, values, and units pass through untouched.
    """
    text = _labels(locale)
    rows: list[dict[str, str]] = []
    for node in spec.nodes:
        if isinstance(node, (SourceNode, SinkNode)):
            rows.append(_row(text("경계", "Boundary"), f"{node.label} {text('압력', 'Pressure')}", node.pressure_pa, "Pa"))
            rows.append(_row(text("경계", "Boundary"), f"{node.label} {text('온도', 'Temperature')}", node.temperature_c, "°C"))
            rows.append(_row(text("경계", "Boundary"), f"{node.label} {text('기체분율', 'Gas fraction')}", node.gas_fraction, "-"))
            rows.append(_row(text("경계", "Boundary"), f"{node.label} {text('총수분율', 'Total water fraction')}", node.total_water_fraction, "-"))
        elif isinstance(node, ClosedNode):
            rows.append(_row(text("경계", "Boundary"), f"{node.label} {text('경계', 'Boundary')}", text("닫힘", "Closed"), ""))
        elif isinstance(node, JunctionNode):
            rows.append(_row(text("경계", "Boundary"), f"{node.label} {text('경계', 'Boundary')}", text("분기", "Branch"), ""))
    for source in spec.massflow_sources:
        rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('관로', 'Flowpath')}", source.flowpath, ""))
        rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('배관', 'Pipe')}", source.pipe, ""))
        rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('구간', 'Section')}", source.section, ""))
        points = source.series or ()
        if points:
            for index, point in enumerate(points, start=1):
                prefix = f"{source.label} {text('시계열', 'Time series')} {index}"
                rows.append(_row(text("유입", "Inflow"), f"{prefix} {text('시간', 'Time')}", point.time_s, "s"))
                rows.append(_row(text("유입", "Inflow"), f"{prefix} {text('질량유량', 'Mass flow')}", point.mass_flow_kg_s, "kg/s"))
                rows.append(_row(text("유입", "Inflow"), f"{prefix} {text('온도', 'Temperature')}", point.temperature_c, "°C"))
                rows.append(_row(text("유입", "Inflow"), f"{prefix} {text('기체분율', 'Gas fraction')}", point.gas_fraction, "-"))
                rows.append(_row(text("유입", "Inflow"), f"{prefix} {text('총수분율', 'Total water fraction')}", point.total_water_fraction, "-"))
        else:
            rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('시간', 'Time')}", source.time_s, "s"))
            rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('질량유량', 'Mass flow')}", source.mass_flow_kg_s, "kg/s"))
            rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('온도', 'Temperature')}", source.temperature_c, "°C"))
            rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('기체분율', 'Gas fraction')}", source.gas_fraction, "-"))
            rows.append(_row(text("유입", "Inflow"), f"{source.label} {text('총수분율', 'Total water fraction')}", source.total_water_fraction, "-"))
    for flowpath in spec.flowpaths:
        for pipe in flowpath.pipes:
            rows.append(_row(text("배관", "Piping"), f"{pipe.label} {text('지름', 'Diameter')}", pipe.diameter_m, "m"))
            rows.append(_row(text("배관", "Piping"), f"{pipe.label} {text('거칠기', 'Roughness')}", pipe.roughness_m, "m"))
            rows.append(_row(text("배관", "Piping"), f"{pipe.label} {text('구간 수', 'Section count')}", pipe.sections, text("개", "")))
            if pipe.centerline_m is None:
                rows.append(_row(text("배관", "Piping"), f"{pipe.label} {text('길이', 'Length')}", pipe.length_m, "m"))
                rows.append(_row(text("배관", "Piping"), f"{pipe.label} {text('높이 변화', 'Elevation change')}", pipe.elevation_m, "m"))
            else:
                rows.append(_row(text("배관", "Piping"), f"{pipe.label} {text('시작', 'Start')}", _point(pipe.centerline_m[0]), "m"))
                rows.append(_row(text("배관", "Piping"), f"{pipe.label} {text('끝', 'End')}", _point(pipe.centerline_m[1]), "m"))
        for valve in spec.equipment:
            if valve.flowpath != flowpath.label:
                continue
            rows.append(_row(text("배관", "Piping"), f"{valve.label} {text('지름', 'Diameter')}", valve.diameter_m, "m"))
            rows.append(_row(text("배관", "Piping"), f"{valve.label} {text('개도', 'Opening')}", valve.opening, "-"))
            for index, point in enumerate(valve.schedule or (), start=1):
                prefix = f"{valve.label} {text('개폐 일정', 'Schedule')} {index}"
                rows.append(_row(text("배관", "Piping"), f"{prefix} {text('시간', 'Time')}", point.time_s, "s"))
                rows.append(_row(text("배관", "Piping"), f"{prefix} {text('개도', 'Opening')}", point.opening, "-"))
            rows.append(_row(text("배관", "Piping"), f"{valve.label} {text('위치', 'Position')}", valve.position, "-"))
    integration = spec.integration
    rows.append(_row(text("해석", "Simulation"), text("끝 시간", "End time"), integration.end_time_s, "s"))
    if integration.trend_interval_s is not None:
        rows.append(_row(text("해석", "Simulation"), text("트렌드 간격", "Trend interval"), integration.trend_interval_s, "s"))
    if integration.profile_interval_s is not None:
        rows.append(_row(text("해석", "Simulation"), text("프로파일 간격", "Profile interval"), integration.profile_interval_s, "s"))
    if integration.output_interval_s is not None:
        rows.append(_row(text("해석", "Simulation"), text("출력 간격", "Output interval"), integration.output_interval_s, "s"))
    if integration.max_dt_s is not None:
        rows.append(_row(text("해석", "Simulation"), text("최대 시간 간격", "Max time step"), integration.max_dt_s, "s"))
    if integration.steady_state is not None:
        rows.append(_row(text("해석", "Simulation"), text("정상상태 전처리", "Steady-state preprocessing"), integration.steady_state, ""))
    if integration.dt_start_s is not None:
        rows.append(_row(text("해석", "Simulation"), text("시작 시간 간격", "Initial time step"), integration.dt_start_s, "s"))
    if integration.min_dt_s is not None:
        rows.append(_row(text("해석", "Simulation"), text("최소 시간 간격", "Min time step"), integration.min_dt_s, "s"))
    for name in spec.outputs:
        rows.append(_row(text("출력", "Output"), text("출력 변수", "Output variable"), name, ""))
    for point in spec.trend_positions or ():
        rows.append(_row(text("출력", "Output"), f"{point.label} {text('트렌드', 'Trend')}", f"{point.pipe} {text('구간', 'Section')} {point.section}", ""))
    return rows


def _field(key: str, value: object, unit: str = "") -> dict[str, str]:
    """One plain row: a stable key the card labels in ko/en, a value, an optional unit."""
    row = {"key": key, "value": _text(value)}
    if unit:
        row["unit"] = unit
    return row


def _range(values: list[float]) -> str:
    return f"{_text(min(values))} – {_text(max(values))}"


def _fluids_draft_display(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    target = tool_side_effects.approval_payload("fluids_draft_mfl", args, paths)
    fields = [
        _field("file", target["mfl_rel"]),
        _field("table_file", target["tab_rel"]),
        _field("label", target["fluid_label"]),
    ]
    fields += [
        _field("component", f"{item['name']} {_text(item['mole_fraction'])}")
        for item in target["components"]
    ]
    fields += [
        _field("model", target["model"]),
        _field("temperature_range", _range(target["temperatures"]), target["temperature_unit"]),
        _field("temperature_points", len(target["temperatures"])),
        _field("pressure_range", _range(target["pressures"]), target["pressure_unit"]),
        _field("pressure_points", len(target["pressures"])),
    ]
    if target["hawater"]:
        fields.append(_field("water_option", "HAWATER"))
    return {"fields": fields}


def _generate_tab_display(args: dict[str, Any], paths: PathBindings, locale: str = "ko") -> dict[str, Any]:
    target = tool_side_effects.approval_payload("fluids_generate_tab", args, paths)
    from .. import native_tab

    text = _labels(locale)
    fields = [
        _field("file", target["tab_rel"]),
        _field("mfl_file", target["mfl_rel"]),
        _field("label", target["fluid_label"]),
    ]
    fields += [
        _field("component", f"{item['name']} {_text(item['mole_fraction'])}")
        for item in target["components"]
    ]
    fields += [
        _field("model", target["model"]),
        _field("temperature_range", _range(target["temperatures"]), target["temperature_unit"]),
        _field("temperature_points", len(target["temperatures"])),
        _field("pressure_range", _range(target["pressures"]), target["pressure_unit"]),
        _field("pressure_points", len(target["pressures"])),
        _field("table_kind", text(native_tab.TABLE_KIND_KO, native_tab.TABLE_KIND_EN)),
    ]
    return {"fields": fields}


def _starter_tab_display(args: dict[str, Any], paths: PathBindings, locale: str = "ko") -> dict[str, Any]:
    target = tool_side_effects.approval_payload("fluids_starter_tab", args, paths)
    from .. import starter_fluids

    text = _labels(locale)
    return {
        "fields": [
            _field("file", target["tab_rel"]),
            _field("label", target["fluid_label"]),
            _field("model", starter_fluids.MODEL),
            _field("temperature_range", _range(list(starter_fluids.TEMPERATURE_RANGE_C)), "degC"),
            _field("pressure_range", _range(list(starter_fluids.PRESSURE_RANGE_BAR)), "bar"),
            _field("table_kind", text(starter_fluids.KIND_KO, starter_fluids.KIND_EN)),
        ]
    }


def _multiflash_open_display(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    target = tool_side_effects.approval_payload("multiflash_open", args, paths)
    fields = [_field("program", "Multiflash")]
    if target["mfl_path"]:
        fields.append(_field("file", _executable_name(target["mfl_path"])))
    return {"fields": fields}


def _genkey_save_display(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    target = tool_side_effects.approval_payload("genkey_save", args, paths)
    return {
        "fields": [
            _field("file", target["save_rel"]),
            _field("topology", target["topology"]),
            _field("end_time", target["endtime_s"], "s"),
            _field("pvt_file", target["pvtfile"]),
        ]
    }


def _run_cancel_display(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    target = tool_side_effects.approval_payload("run_cancel", args, paths)
    return {"fields": [_field("run_id", target["run_id"])]}


def _sweep_cancel_display(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    target = tool_side_effects.approval_payload("sweep_cancel", args, paths)
    return {"fields": [_field("sweep_id", target["sweep_id"])]}


def _sweep_execute_display(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    target = tool_side_effects.approval_payload("sweep_execute", args, paths)
    try:
        state = sweep_selection.get_state(target["sweep_id"])
    except (sweep_selection.UnknownSweepError, genkey_static.OlgaInputError) as exc:
        raise ToolError("The sweep preview is no longer available; preview the sweep again.") from exc
    if state.plan_id != target["plan_id"]:
        raise ToolError("The sweep plan changed; preview the sweep again.")
    return {
        "fields": [
            _field("sweep_id", state.sweep_id),
            _field("case", state.base.name),
            _field("case_count", len(state.cases)),
            _field("timeout", state.timeout_s, "s"),
            _field("plan_id", state.plan_id),
        ]
    }


_FIELD_BUILDERS: dict[str, Callable[[dict[str, Any], PathBindings], dict[str, Any]]] = {
    "fluids_draft_mfl": _fluids_draft_display,
    "multiflash_open": _multiflash_open_display,
    "genkey_save": _genkey_save_display,
    "run_cancel": _run_cancel_display,
    "sweep_cancel": _sweep_cancel_display,
    "sweep_execute": _sweep_execute_display,
}


def _plan_run_fields(
    args: dict[str, Any], paths: PathBindings, previewer: Previewer, locale: str
) -> list[dict[str, str]]:
    """What a single run card shows, minus hashes: the case, runtime, executable and output."""
    try:
        shown = build("run_execute", args, paths, previewer, locale)
    except (genkey_static.OlgaInputError, workspace.WorkspaceError) as exc:
        raise ToolError("The run could not be previewed, so the plan was not offered.") from exc
    return [
        _field("run_case", shown["case"]),
        _field("runtime", shown["runtime_id"]),
        _field("executable", shown["executable"]),
        _field("output", shown["output_target"]),
        _field("timeout", shown["timeout_s"], "s"),
    ]


def _plan_display(
    args: dict[str, Any], paths: PathBindings, previewer: Previewer, locale: str
) -> dict[str, Any]:
    """One row per step: pinned facts now, and what a bound step cannot know yet."""
    payload = tool_side_effects.approval_payload(plan_model.PLAN_KIND, args, paths)
    steps = plan_model.canonical_steps(args.get("steps"))
    rows: list[dict[str, Any]] = []
    for number, (step, pinned) in enumerate(zip(steps, payload["steps"]), start=1):
        kind = step["kind"]
        row: dict[str, Any] = {"index": number, "kind": kind}
        if kind == "fluids_draft_mfl":
            row["fields"] = _fluids_draft_display(step["args"], paths)["fields"]
        elif kind == "fluids_generate_tab":
            row["fields"] = _generate_tab_display(step["args"], paths, locale)["fields"]
        elif kind == "case_publish":
            row["fields"] = [_field("file", pinned["payload"]["destination_rel"])]
            row["inputs"] = _case_publish_display(step["args"], locale=locale)["inputs"]
        elif pinned["bind"] is not None:
            row["fields"] = [_field("timeout", pinned["timeout_s"], "s")]
            row["bound_to"] = pinned["bind"]["source_from_step"]
            row["unknown"] = ["run_case", "runtime", "executable", "output"]
        else:
            row["fields"] = _plan_run_fields(step["args"], paths, previewer, locale)
        rows.append(row)
    return {"plan": {"steps": rows}}


def _case_publish_display(args: dict[str, Any], locale: str = "ko") -> dict[str, Any]:
    transaction_id = args.get("transaction_id")
    if not isinstance(transaction_id, str):
        raise ToolError("The pending case publication is incomplete.")
    try:
        stored = case_transactions.load_transaction(transaction_id)
    except (OSError, TransactionStoreError) as exc:
        raise ToolError(str(exc)) from exc
    if (
        args.get("source_hash") != stored.source_hash
        or args.get("compiled_hash") != stored.compiled_hash
        or args.get("context_generation") != stored.context_generation
        or not stored.publishable
        or not stored.validation_clean
    ):
        raise ToolError("The pending case publication no longer matches its reviewed transaction.")
    try:
        spec = case_spec_recovery.recover_case_spec(stored.compiled)
    except UnsupportedSourceError as exc:
        raise ToolError(str(exc)) from exc
    return {"inputs": reviewed_inputs(spec, locale=locale)}


def build(
    action_kind: str,
    args: dict[str, Any],
    paths: PathBindings = DEFAULT_PATH_BINDINGS,
    previewer: Previewer = runner.preview_run,
    locale: str = "ko",
) -> dict[str, Any]:
    """Return facts independently re-derived by the server, never model display data."""
    if action_kind == plan_model.PLAN_KIND:
        return _plan_display(args, paths, previewer, locale)
    if action_kind == "case_publish":
        return _case_publish_display(args, locale=locale)
    if action_kind == "fluids_generate_tab":
        return _generate_tab_display(args, paths, locale)
    if action_kind == "fluids_starter_tab":
        return _starter_tab_display(args, paths, locale)
    field_builder = _FIELD_BUILDERS.get(action_kind)
    if field_builder is not None:
        return field_builder(args, paths)
    if action_kind != "run_execute":
        return {}
    source_value = args.get("source") or workspace.active_path()
    selection_id = str(args.get("selection_id") or "")
    if not source_value or not selection_id:
        raise ToolError("The pending run approval is incomplete.")
    source = Path(paths.input_file(source_value, {".genkey"}))
    timeout_s = runner.require_timeout_seconds(args.get("timeout_s", 3600))
    preview = previewer(str(source), timeout_s)
    if str(preview.get("selection_id") or "") != selection_id:
        raise ToolError("The runtime selection changed; preview the run again.")
    detection = preview.get("detection")
    detection = detection if isinstance(detection, dict) else {}
    display = {
        "case": source.name,
        "selection_id": selection_id,
        "runtime_id": str(preview.get("runtime_id") or ""),
        "executable": _executable_name(detection.get("exe")),
        "output_target": "managed-run-sandbox",
        "source_sha256": file_sha256(source),
        "timeout_s": int(preview.get("timeout_s") or timeout_s),
        "context_generation": int(preview.get("context_generation") or 0),
    }
    step_warnings = pvt_range.pressure_step_warnings(source, "en" if locale == "en" else "ko")
    if step_warnings:
        display["warnings"] = step_warnings
    return display
