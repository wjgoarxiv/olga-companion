"""Pure ordered application of typed CaseSpec edit operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing_extensions import override
from .case_spec import CaseSpec
from .case_spec_types import FlowpathSpec, JunctionNode, Node, PipeSpec, SinkNode, SourceNode
from .case_spec_validation import JsonObject, JsonValue
from .case_transaction_models import (
    EditOperation,
    RenameNode,
    SemanticDiff,
    SetBoundaryPressure,
    SetBoundaryTemperature,
    SetFluid,
    SetIntegration,
    SetOutputs,
    SetPipeGeometry,
    SetPipeRoughness,
    SetPipeSections,
    SetSourceMassflow,
    SetThermal,
    SetValveOpening,
)


@dataclass(frozen=True, slots=True)
class UnknownTargetError(RuntimeError):
    identity: str

    @override
    def __str__(self) -> str:
        return f"Edit target does not exist: {self.identity}"


class UnsupportedEditError(RuntimeError):
    """A typed edit that the target pipe or valve cannot take."""


def _replace_pipe(
    spec: CaseSpec, operation: SetPipeGeometry | SetPipeSections | SetPipeRoughness
) -> tuple[CaseSpec, PipeSpec]:
    replaced: PipeSpec | None = None
    flowpaths: list[FlowpathSpec] = []
    for flowpath in spec.flowpaths:
        if flowpath.label != operation.flowpath:
            flowpaths.append(flowpath)
            continue
        pipes: list[PipeSpec] = []
        for pipe in flowpath.pipes:
            if pipe.label != operation.pipe:
                pipes.append(pipe)
                continue
            match operation:
                case SetPipeGeometry(diameter_m=diameter, elevation_offset_m=offset):
                    points = pipe.centerline_m
                    if offset is not None and points is None:
                        raise UnsupportedEditError(
                            f"{operation.flowpath}/{operation.pipe} is a length/elevation pipe "
                            "with no coordinates to shift"
                        )
                    if offset is not None:
                        points = tuple((x, y + offset, z) for x, y, z in points)
                    updates: dict[str, JsonValue] = {"centerline_m": points}
                    if diameter is not None:
                        updates["diameter_m"] = diameter
                    replaced = pipe.model_copy(update=updates)
                case SetPipeSections(sections=sections):
                    # New even sections replace any graded lengths the pipe had.
                    replaced = pipe.model_copy(update={"sections": sections, "segment_lengths_m": None})
                case SetPipeRoughness(roughness_m=roughness):
                    replaced = pipe.model_copy(update={"roughness_m": roughness})
            pipes.append(replaced)
        flowpaths.append(flowpath.model_copy(update={"pipes": tuple(pipes)}))
    if replaced is None:
        raise UnknownTargetError(f"{operation.flowpath}/{operation.pipe}")
    return spec.model_copy(update={"flowpaths": tuple(flowpaths)}), replaced


def apply_operation(
    spec: CaseSpec, operation: EditOperation
) -> tuple[CaseSpec, SemanticDiff]:
    """Apply one typed operation without prematurely validating the whole graph."""
    match operation:
        case SetIntegration(end_time_s=end_time):
            before = spec.integration.end_time_s
            updated = spec.model_copy(update={
                "integration": spec.integration.model_copy(update={"end_time_s": end_time})
            })
            return updated, SemanticDiff("integration.end_time_s", before, end_time)
        case SetPipeGeometry(flowpath=flowpath, pipe=pipe):
            parent = next((item for item in spec.flowpaths if item.label == flowpath), None)
            previous = next((item for item in parent.pipes if item.label == pipe), None) if parent else None
            updated, replacement = _replace_pipe(spec, operation)
            geometry_before: JsonObject = {
                "diameter_m": previous.diameter_m,
                "centerline_m": previous.centerline_m,
            } if previous else {}
            after: JsonObject = {
                "diameter_m": replacement.diameter_m,
                "centerline_m": replacement.centerline_m,
            }
            return updated, SemanticDiff(
                f"flowpaths.{flowpath}.pipes.{pipe}.geometry", geometry_before, after
            )
        case SetPipeSections(flowpath=flowpath, pipe=pipe):
            parent = next((item for item in spec.flowpaths if item.label == flowpath), None)
            previous = next((item for item in parent.pipes if item.label == pipe), None) if parent else None
            updated, replacement = _replace_pipe(spec, operation)
            return updated, SemanticDiff(
                f"flowpaths.{flowpath}.pipes.{pipe}.sections",
                previous.sections if previous else None, replacement.sections,
            )
        case SetBoundaryPressure(node=label, pressure_pa=pressure):
            found = False
            nodes: list[Node] = []
            pressure_before: float | None = None
            for node in spec.nodes:
                if node.label != label:
                    nodes.append(node)
                    continue
                match node:
                    case SourceNode() | SinkNode():
                        pressure_before = node.pressure_pa
                        nodes.append(node.model_copy(update={"pressure_pa": pressure}))
                        found = True
                    case JunctionNode():
                        raise UnknownTargetError(f"boundary:{label}")
            if not found:
                raise UnknownTargetError(f"boundary:{label}")
            return spec.model_copy(update={"nodes": tuple(nodes)}), SemanticDiff(
                f"nodes.{label}.pressure_pa", pressure_before, pressure
            )
        case SetPipeRoughness(flowpath=flowpath, pipe=pipe):
            parent = next((item for item in spec.flowpaths if item.label == flowpath), None)
            previous = next((item for item in parent.pipes if item.label == pipe), None) if parent else None
            updated, replacement = _replace_pipe(spec, operation)
            return updated, SemanticDiff(
                f"flowpaths.{flowpath}.pipes.{pipe}.roughness_m",
                previous.roughness_m if previous else None, replacement.roughness_m,
            )
        case SetBoundaryTemperature(node=label, temperature_c=temperature):
            nodes_t: list[Node] = []
            temperature_before: float | None = None
            for node in spec.nodes:
                if node.label != label:
                    nodes_t.append(node)
                    continue
                match node:
                    case SourceNode() | SinkNode():
                        temperature_before = node.temperature_c
                        nodes_t.append(node.model_copy(update={"temperature_c": temperature}))
                    case JunctionNode():
                        raise UnknownTargetError(f"boundary:{label}")
            if temperature_before is None:
                raise UnknownTargetError(f"boundary:{label}")
            return spec.model_copy(update={"nodes": tuple(nodes_t)}), SemanticDiff(
                f"nodes.{label}.temperature_c", temperature_before, temperature
            )
        case SetThermal(thermal=thermal):
            return spec.model_copy(update={"thermal": thermal}), SemanticDiff(
                "thermal",
                spec.thermal.model_dump(mode="json"),
                thermal.model_dump(mode="json"),
            )
        case SetFluid(fluid_label=fluid_label):
            return spec.model_copy(update={"fluid_label": fluid_label}), SemanticDiff(
                "fluid_label", spec.fluid_label, fluid_label
            )
        case SetOutputs(outputs=outputs):
            return spec.model_copy(update={"outputs": outputs}), SemanticDiff(
                "outputs", list(spec.outputs), list(outputs)
            )
        case SetSourceMassflow(label=label):
            found = False
            sources = []
            before: JsonObject = {}
            after: JsonObject = {}
            point_update: dict[str, float] = {"mass_flow_kg_s": operation.mass_flow_kg_s}
            if operation.temperature_c is not None:
                point_update["temperature_c"] = operation.temperature_c
            if operation.gas_fraction is not None:
                point_update["gas_fraction"] = operation.gas_fraction
            if operation.total_water_fraction is not None:
                point_update["total_water_fraction"] = operation.total_water_fraction
            complete_point = (
                operation.temperature_c is not None
                and operation.gas_fraction is not None
                and operation.total_water_fraction is not None
            )
            for source in spec.massflow_sources:
                if source.label != label:
                    sources.append(source)
                    continue
                before = {
                    "mass_flow_kg_s": source.mass_flow_kg_s,
                    "temperature_c": source.temperature_c,
                    "gas_fraction": source.gas_fraction,
                    "total_water_fraction": source.total_water_fraction,
                }
                if source.series:
                    before["series"] = [
                        point.model_dump(mode="json") for point in source.series
                    ]
                if source.series and not complete_point:
                    series = tuple(
                        point.model_copy(update=point_update) for point in source.series
                    )
                    first = series[0]
                    updated_source = source.model_copy(update={
                        "series": series,
                        "time_s": first.time_s,
                        "mass_flow_kg_s": first.mass_flow_kg_s,
                        "temperature_c": first.temperature_c,
                        "gas_fraction": first.gas_fraction,
                        "total_water_fraction": first.total_water_fraction,
                    })
                else:
                    updated_source = source.model_copy(update={**point_update, "series": None})
                after = {
                    "mass_flow_kg_s": updated_source.mass_flow_kg_s,
                    "temperature_c": updated_source.temperature_c,
                    "gas_fraction": updated_source.gas_fraction,
                    "total_water_fraction": updated_source.total_water_fraction,
                }
                if source.series or updated_source.series:
                    after["series"] = [
                        point.model_dump(mode="json")
                        for point in (updated_source.series or ())
                    ]
                sources.append(updated_source)
                found = True
            if not found:
                raise UnknownTargetError(f"massflow:{label}")
            return spec.model_copy(update={"massflow_sources": tuple(sources)}), SemanticDiff(
                f"massflow_sources.{label}", before, after
            )
        case SetValveOpening(label=label, opening=opening):
            found_valve = False
            valves = []
            opening_before: float | None = None
            for valve in spec.equipment:
                if valve.label != label:
                    valves.append(valve)
                    continue
                opening_before = valve.opening
                # A fixed opening replaces any schedule the valve had.
                valves.append(valve.model_copy(update={"opening": opening, "schedule": None}))
                found_valve = True
            if not found_valve:
                raise UnknownTargetError(f"valve:{label}")
            return spec.model_copy(update={"equipment": tuple(valves)}), SemanticDiff(
                f"equipment.{label}.opening", opening_before, opening
            )
        case RenameNode(node=label, new_label=new_label):
            if not any(node.label == label for node in spec.nodes):
                raise UnknownTargetError(f"node:{label}")
            topology_nodes = tuple(
                node.model_copy(update={"label": new_label}) if node.label == label else node
                for node in spec.nodes
            )
            flowpaths = tuple(
                flowpath.model_copy(update={
                    "from_node": new_label if flowpath.from_node == label else flowpath.from_node,
                    "to_node": new_label if flowpath.to_node == label else flowpath.to_node,
                })
                for flowpath in spec.flowpaths
            )
            return spec.model_copy(
                update={"nodes": topology_nodes, "flowpaths": flowpaths}
            ), SemanticDiff(
                f"nodes.{label}.label", label, new_label
            )
