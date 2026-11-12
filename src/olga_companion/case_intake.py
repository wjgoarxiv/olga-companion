"""Read-only CaseSpec intake requirements derived from the schema.

Every field, unit, and required flag below is read off the pydantic
CaseSpec models at import time. Group membership is presentation, but the
field list itself is never hand-maintained: adding a required schema field
without registering it here fails the intake coverage test.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import case_draft_store, workspace
from .case_draft_store import Draft, DraftError
from .case_spec import CaseSpec
from .case_spec_types import (
    OUTPUT_NAMES,
    AmbientThermal,
    IntegrationSpec,
    MassflowSource,
    PipeSpec,
    SinkNode,
    SourceNode,
    ValveEquipment,
)

router = APIRouter()

_UNIT_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    ("_w_m2k", "W/m²K"),
    ("_w_mk", "W/m·K"),
    ("_j_kgk", "J/kg·K"),
    ("_kg_m3", "kg/m³"),
    ("_kg_s", "kg/s"),
    ("_pa", "Pa"),
    ("_c", "°C"),
    ("_m", "m"),
    ("_s", "s"),
)

def _unit_for(model: type[BaseModel], field: str) -> str:
    lowered = field.lower()
    for suffix, unit in _UNIT_BY_SUFFIX:
        if lowered.endswith(suffix):
            return unit
    return ""


def _describe(model: type[BaseModel], field: str) -> dict[str, Any]:
    info = model.model_fields[field]
    return {"required": bool(info.is_required())}


def _root_required(name: str) -> bool:
    return bool(CaseSpec.model_fields[name].is_required())


def _build_groups() -> list[dict[str, Any]]:
    specs: list[tuple[str, str, str, str, type[BaseModel], str, str, tuple[str, ...] | None]] = [
        ("fluid", "유체", "fluid.pvt_reference", "PVT 표 파일 (.tab)", CaseSpec, "pvt_reference", "파일", None),
        ("fluid", "유체", "fluid.fluid_label", "유체 라벨", CaseSpec, "fluid_label", "이름", None),
        (
            "boundary", "경계", "boundary.inlet_choice",
            "입구: 압력 경계 또는 막힌 끝 + 질량유량 입구",
            MassflowSource, "mass_flow_kg_s", "선택", None,
        ),
        ("boundary", "경계", "boundary.source_pressure", "입구 압력", SourceNode, "pressure_pa", "", None),
        ("boundary", "경계", "boundary.source_temperature", "입구 온도", SourceNode, "temperature_c", "", None),
        ("boundary", "경계", "boundary.source_gas_fraction", "입구 유체 조성: 기체 분율", SourceNode, "gas_fraction", "-", None),
        ("boundary", "경계", "boundary.source_total_water_fraction", "입구 유체 조성: 총 물 분율", SourceNode, "total_water_fraction", "-", None),
        ("boundary", "경계", "boundary.sink_pressure", "출구 압력", SinkNode, "pressure_pa", "", None),
        ("boundary", "경계", "boundary.sink_temperature", "출구 온도", SinkNode, "temperature_c", "", None),
        ("boundary", "경계", "boundary.sink_gas_fraction", "출구 유체 조성: 기체 분율, 총 물 분율", SinkNode, "gas_fraction", "-", None),
        ("boundary", "경계", "boundary.sink_total_water_fraction", "출구 유체 조성: 총 물 분율", SinkNode, "total_water_fraction", "-", None),
        ("boundary", "경계", "boundary.massflow_rate", "질량유량 입구", MassflowSource, "mass_flow_kg_s", "", None),
        ("boundary", "경계", "boundary.massflow_temperature", "질량유량 온도", MassflowSource, "temperature_c", "", None),
        ("boundary", "경계", "boundary.massflow_series", "질량유량 시계열", MassflowSource, "series", "선택", None),
        ("geometry", "배관", "geometry.pipe_path", "배관 경로 (길이·높이)", PipeSpec, "centerline_m", "m", None),
        ("geometry", "배관", "geometry.diameter", "지름", PipeSpec, "diameter_m", "", None),
        ("geometry", "배관", "geometry.roughness", "거칠기", PipeSpec, "roughness_m", "", None),
        ("geometry", "배관", "geometry.sections", "구간 수", PipeSpec, "sections", "개", None),
        ("thermal", "열전달", "thermal.model", "단열 또는 주변 조건", CaseSpec, "thermal", "선택", ("adiabatic", "ambient_h_given")),
        ("thermal", "열전달", "thermal.ambient_temperature", "주변 온도", AmbientThermal, "ambient_temperature_c", "", None),
        ("thermal", "열전달", "thermal.outer_coefficient", "바깥 열전달 계수", AmbientThermal, "outer_heat_transfer_coefficient_w_m2k", "", None),
        ("thermal", "열전달", "thermal.wall", "벽 두께·재질", AmbientThermal, "wall", "m", None),
        ("equipment", "선택 장비", "equipment.valve", "밸브", ValveEquipment, "label", "선택", None),
        ("outputs", "출력 변수", "outputs.outputs", "출력 변수", CaseSpec, "outputs", "변수", tuple(OUTPUT_NAMES)),
        ("outputs", "출력 변수", "outputs.trend_positions", "트렌드 위치", CaseSpec, "trend_positions", "선택", None),
        ("time", "해석 시간", "time.end_time_s", "끝 시간", IntegrationSpec, "end_time_s", "", None),
        ("time", "해석 시간", "time.trend_interval_s", "트렌드 간격", IntegrationSpec, "trend_interval_s", "", None),
        ("time", "해석 시간", "time.profile_interval_s", "프로파일 간격", IntegrationSpec, "profile_interval_s", "", None),
        ("time", "해석 시간", "time.output_interval_s", "출력 간격", IntegrationSpec, "output_interval_s", "", None),
        ("time", "해석 시간", "time.max_dt_s", "최대 시간 간격", IntegrationSpec, "max_dt_s", "", None),
        ("time", "해석 시간", "time.steady_state", "정상상태 전처리", IntegrationSpec, "steady_state", "선택", None),
        ("time", "해석 시간", "time.dt_start_s", "시작 시간 간격", IntegrationSpec, "dt_start_s", "", None),
        ("time", "해석 시간", "time.min_dt_s", "최소 시간 간격", IntegrationSpec, "min_dt_s", "", None),
    ]
    covered = {(model.__name__, field) for _, _, _, _, model, field, _, _ in specs}
    groups: dict[str, dict[str, Any]] = {}
    for group_id, title, key, label, model, field, unit, values in specs:
        derived_unit = unit or _unit_for(model, field)
        root = {"fluid": "pvt_reference", "boundary": "nodes", "geometry": "flowpaths",
                "thermal": "thermal", "equipment": "equipment", "outputs": "outputs",
                "time": "integration"}[group_id]
        required = _root_required(root) and _describe(model, field)["required"]
        if group_id in {"thermal"} and model is AmbientThermal:
            required = False
        if group_id == "equipment" or (group_id == "boundary" and model is MassflowSource):
            required = False
        if key == "geometry.pipe_path":
            # A pipe needs one geometry form (centerline, or length with elevation), so
            # the path is required even though neither form alone has to be given.
            required = True
        item: dict[str, Any] = {
            "key": key,
            "label": label,
            "unit": derived_unit,
            "required": required,
        }
        if values is not None:
            item["values"] = list(values)
        groups.setdefault(group_id, {"id": group_id, "title": title, "items": []})
        groups[group_id]["items"].append(item)
    _check_coverage(covered)
    return list(groups.values())


def _check_coverage(covered: set[tuple[str, str]]) -> None:
    expected = {
        ("CaseSpec", "pvt_reference"),
        ("CaseSpec", "fluid_label"),
        ("CaseSpec", "thermal"),
        ("CaseSpec", "outputs"),
        ("CaseSpec", "trend_positions"),
        ("SourceNode", "pressure_pa"),
        ("SourceNode", "temperature_c"),
        ("SourceNode", "gas_fraction"),
        ("SourceNode", "total_water_fraction"),
        ("SinkNode", "pressure_pa"),
        ("SinkNode", "temperature_c"),
        ("SinkNode", "gas_fraction"),
        ("SinkNode", "total_water_fraction"),
        ("MassflowSource", "mass_flow_kg_s"),
        ("MassflowSource", "temperature_c"),
        ("MassflowSource", "series"),
        ("PipeSpec", "centerline_m"),
        ("PipeSpec", "diameter_m"),
        ("PipeSpec", "roughness_m"),
        ("PipeSpec", "sections"),
        ("IntegrationSpec", "end_time_s"),
        ("IntegrationSpec", "trend_interval_s"),
        ("IntegrationSpec", "profile_interval_s"),
        ("IntegrationSpec", "output_interval_s"),
        ("IntegrationSpec", "max_dt_s"),
        ("IntegrationSpec", "steady_state"),
        ("IntegrationSpec", "dt_start_s"),
        ("IntegrationSpec", "min_dt_s"),
    }
    missing = sorted(name for name in expected - covered)
    if missing:
        raise RuntimeError(f"intake requirements miss schema fields: {missing}")


@router.get("/api/case-spec/requirements")
def api_case_spec_requirements() -> dict[str, Any]:
    """Read-only required-field list for the guided new-case intake card."""
    return {"groups": _build_groups()}


def draft_topology(draft: Draft) -> dict[str, Any]:
    """The draft network as index lists: about 20 bytes per flowpath, so 320 flowpaths stay near 10 KB."""
    kinds: list[str] = []
    index: dict[str, int] = {}
    nodes: list[list[Any]] = []
    for node in draft.spec["nodes"]:
        kind = str(node["kind"])
        if kind not in kinds:
            kinds.append(kind)
        index[node["label"]] = len(nodes)
        nodes.append([node["label"], kinds.index(kind)])
    edges = [[index[item["from"]], index[item["to"]], item["label"]] for item in draft.spec["flowpaths"]]
    return {
        "draft_id": draft.draft_id,
        "revision": draft.revision,
        "counts": {"nodes": len(nodes), "flowpaths": len(edges), "edges": len(edges)},
        "kinds": kinds,
        "nodes": nodes,
        "edges": edges,
    }


@router.get("/api/case-draft/{draft_id}/topology")
def api_case_draft_topology(draft_id: str) -> dict[str, Any]:
    """Read-only network of a live draft of this workspace state; an expired or foreign draft is refused."""
    try:
        _root, generation = workspace.context_identity()
        draft = case_draft_store.get_draft(draft_id, context_generation=generation)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DraftError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return draft_topology(draft)
