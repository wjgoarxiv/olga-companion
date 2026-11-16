"""Typed, side-effect-free CaseSpec v2 trust boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import (
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from .case_spec_dispatch_schema import inline_case_spec_schema
from .case_spec_types import (
    GEOMETRY_TOLERANCE_M,
    ClosedCaseModel,
    ClosedNode,
    FlowpathSpec,
    FluidLabel,
    InitialConditions,
    IntegrationSpec,
    JunctionNode,
    MassflowSource,
    Node,
    OUTPUT_NAMES,
    OutputName,
    Point,
    PvtReference,
    SinkNode,
    SourceNode,
    Thermal,
    TrendPosition,
    ValveEquipment,
    point_distance,
)
from .case_spec_validation import (
    CaseSpecValidationResult,
    JsonObject,
    JsonValue,
    capability_matrix,
    closed_inlet_zero_source_issue,
    invalid_result,
    legacy_version_issue,
    steady_state_off_issue,
    unsupported_equipment_issue,
    validation_issue,
)


V2_MAX_SOURCES = 32
V2_MAX_VALVES = 16
V3_MAX_SOURCES = 128
V3_MAX_VALVES = 256
MAX_TOTAL_SECTIONS = 5_000
# A synthetic 319-flowpath network with 11,634 sections compiled and passed the toolkit
# check in about 0.5 s (tests/test_case_scale.py), so v3 takes twice the v2 total.
V3_MAX_TOTAL_SECTIONS = 10_000


class CaseSpec(ClosedCaseModel):
    version: Literal["2", "3"]
    nodes: Annotated[tuple[Node, ...], Field(min_length=2, max_length=256)]
    flowpaths: Annotated[tuple[FlowpathSpec, ...], Field(min_length=1, max_length=512)]
    pvt_reference: PvtReference
    fluid_label: FluidLabel
    thermal: Thermal
    integration: IntegrationSpec
    outputs: Annotated[
        tuple[OutputName, ...], Field(min_length=1, max_length=len(OUTPUT_NAMES))
    ]
    massflow_sources: Annotated[
        tuple[MassflowSource, ...], Field(default=(), max_length=V3_MAX_SOURCES)
    ]
    equipment: Annotated[
        tuple[ValveEquipment, ...], Field(default=(), max_length=V3_MAX_VALVES)
    ]
    trend_positions: tuple[TrendPosition, ...] | None = None
    initial_conditions: InitialConditions | None = None

    @property
    def uses_length_geometry(self) -> bool:
        return any(pipe.uses_length for flowpath in self.flowpaths for pipe in flowpath.pipes)

    @field_validator("nodes")
    @classmethod
    def canonical_nodes(cls, nodes: tuple[Node, ...]) -> tuple[Node, ...]:
        return tuple(sorted(nodes, key=lambda node: node.label))

    @field_validator("flowpaths")
    @classmethod
    def canonical_flowpaths(
        cls, flowpaths: tuple[FlowpathSpec, ...]
    ) -> tuple[FlowpathSpec, ...]:
        return tuple(sorted(flowpaths, key=lambda flowpath: flowpath.label))

    @field_validator("outputs")
    @classmethod
    def canonical_outputs(
        cls, outputs: tuple[OutputName, ...]
    ) -> tuple[OutputName, ...]:
        if len(set(outputs)) != len(outputs):
            raise PydanticCustomError("duplicate_output", "output names must be unique")
        return tuple(sorted(outputs))

    @field_validator("massflow_sources")
    @classmethod
    def canonical_massflow_sources(
        cls, sources: tuple[MassflowSource, ...]
    ) -> tuple[MassflowSource, ...]:
        return tuple(sorted(sources, key=lambda source: source.label))

    @field_validator("equipment")
    @classmethod
    def canonical_equipment(
        cls, equipment: tuple[ValveEquipment, ...]
    ) -> tuple[ValveEquipment, ...]:
        return tuple(sorted(equipment, key=lambda valve: valve.label))

    @model_validator(mode="after")
    def validate_network(self) -> CaseSpec:
        _require_version_grammar(self)
        labels = [node.label for node in self.nodes]
        labels.extend(source.label for source in self.massflow_sources)
        labels.extend(valve.label for valve in self.equipment)
        labels.extend(point.label for point in self.trend_positions or ())
        labels.extend(flowpath.label for flowpath in self.flowpaths)
        labels.extend(
            pipe.label for flowpath in self.flowpaths for pipe in flowpath.pipes
        )
        labels.extend(_generated_position_labels(self))
        if len(set(labels)) != len(labels):
            raise PydanticCustomError(
                "duplicate_label", "labels must be globally unique"
            )
        nodes = {node.label: node for node in self.nodes}
        references = {
            label
            for flowpath in self.flowpaths
            for label in (flowpath.from_node, flowpath.to_node)
        }
        if not references.issubset(nodes):
            raise PydanticCustomError(
                "unknown_reference", "flowpath endpoint does not name a node"
            )
        if references != set(nodes) or not _is_connected(set(nodes), self.flowpaths):
            raise PydanticCustomError(
                "disconnected_topology", "all nodes must form one connected network"
            )
        for flowpath in self.flowpaths:
            source, target = nodes[flowpath.from_node], nodes[flowpath.to_node]
            if (
                source.kind == "sink"
                or target.kind in {"source", "closed"}
                or source.label == target.label
            ):
                raise PydanticCustomError(
                    "invalid_topology", "source/sink flow direction is invalid"
                )
        has_inlet = any(node.kind in {"source", "closed"} for node in self.nodes)
        has_sink = any(node.kind == "sink" for node in self.nodes)
        if not has_inlet or not has_sink:
            raise PydanticCustomError(
                "invalid_topology", "network requires an inlet and a sink"
            )
        if not any(node.kind in {"source", "sink"} for node in self.nodes):
            raise PydanticCustomError(
                "pressure_boundary_required",
                "network requires at least one PRESSURE boundary",
            )
        limit = V3_MAX_TOTAL_SECTIONS if self.version == "3" else MAX_TOTAL_SECTIONS
        if sum(pipe.sections for flowpath in self.flowpaths for pipe in flowpath.pipes) > limit:
            raise PydanticCustomError(
                "invalid_geometry", f"total section count exceeds {limit}"
            )
        _require_verified_degrees(self.nodes, self.flowpaths, pass_through=self.version == "3")
        if _has_directed_cycle(self.nodes, self.flowpaths):
            raise PydanticCustomError(
                "invalid_topology",
                "directed cycles are outside CaseSpec; build a circulation loop as two "
                "parallel flowpaths that both run from the bottom junction to the top junction",
            )
        if not self.uses_length_geometry:
            _require_shared_node_geometry(self.flowpaths)
        _require_massflow_sources(self)
        _require_closed_inlets(self)
        _require_valves(self)
        _require_trend_positions(self)
        refused = steady_state_off_issue(self) or closed_inlet_zero_source_issue(self)
        if refused is not None:
            raise PydanticCustomError(str(refused["code"]), str(refused["message"]))
        return self


def _require_version_grammar(spec: CaseSpec) -> None:
    """v2 keeps its verified grammar; the v3 forms and larger caps need version "3"."""
    pipes = [pipe for flowpath in spec.flowpaths for pipe in flowpath.pipes]
    if spec.version == "3":
        if len({pipe.uses_length for pipe in pipes}) > 1:
            raise PydanticCustomError(
                "invalid_geometry", "use length_m/elevation_m on every pipe or on none"
            )
        if spec.initial_conditions is not None and spec.integration.steady_state is not False:
            raise PydanticCustomError(
                "initial_conditions_need_steady_state_off",
                "initial_conditions replace the steady-state pre-processor; set integration.steady_state to false",
            )
        return
    if spec.initial_conditions is not None:
        raise PydanticCustomError("unsupported_initial_conditions", "initial_conditions need version 3")
    if any(pipe.uses_length or pipe.segment_lengths_m is not None for pipe in pipes):
        raise PydanticCustomError(
            "invalid_geometry", "length_m, elevation_m and segment_lengths_m need version 3"
        )
    if any(valve.schedule is not None for valve in spec.equipment):
        raise PydanticCustomError("unsupported_equipment", "valve schedules need version 3")
    if len(spec.equipment) > V2_MAX_VALVES or len(spec.massflow_sources) > V2_MAX_SOURCES:
        raise PydanticCustomError(
            "v2_item_limit", "version 2 takes at most 16 valves and 32 mass-flow sources"
        )


def _generated_position_labels(spec: CaseSpec) -> tuple[str, ...]:
    """POSITION names the compiler will emit, so they stay out of the user's labels."""
    labels = [f"POS_{source.label}" for source in spec.massflow_sources]
    if spec.trend_positions:
        return tuple(labels)
    for flowpath in spec.flowpaths:
        first, last = flowpath.pipes[0], flowpath.pipes[-1]
        outlet = f"POS_{flowpath.label}"
        inlet = f"POS_{flowpath.label}_1"
        if (first.label, 1) == (last.label, int(last.sections)):
            labels.append(outlet)
        else:
            labels.extend((inlet, outlet))
    return tuple(labels)


def _require_trend_positions(spec: CaseSpec) -> None:
    if not spec.trend_positions:
        return
    pipes = {
        pipe.label: pipe
        for flowpath in spec.flowpaths
        for pipe in flowpath.pipes
    }
    for point in spec.trend_positions:
        pipe = pipes.get(point.pipe)
        if pipe is None:
            raise PydanticCustomError(
                "unknown_reference", "trend position does not name a pipe"
            )
        if point.section > pipe.sections:
            raise PydanticCustomError(
                "invalid_geometry", "trend position section is outside the pipe"
            )


def _require_closed_inlets(spec: CaseSpec) -> None:
    fed = {source.flowpath for source in spec.massflow_sources}
    for node in spec.nodes:
        if node.kind != "closed":
            continue
        attached = [
            flowpath.label
            for flowpath in spec.flowpaths
            if node.label in {flowpath.from_node, flowpath.to_node}
        ]
        if not any(label in fed for label in attached):
            raise PydanticCustomError(
                "closed_node_without_inflow",
                "a closed node needs a mass-flow inlet on its flowpath",
            )


def _require_massflow_sources(spec: CaseSpec) -> None:
    flowpaths = {flowpath.label: flowpath for flowpath in spec.flowpaths}
    for source in spec.massflow_sources:
        flowpath = flowpaths.get(source.flowpath)
        if flowpath is None:
            raise PydanticCustomError(
                "unknown_reference", "mass-flow source does not name a flowpath"
            )
        pipes = {pipe.label: pipe for pipe in flowpath.pipes}
        pipe = pipes.get(source.pipe)
        if pipe is None:
            raise PydanticCustomError(
                "unknown_reference", "mass-flow source pipe is not on that flowpath"
            )
        if source.section > pipe.sections:
            raise PydanticCustomError(
                "invalid_geometry", "mass-flow source section is outside the pipe"
            )


def _require_valves(spec: CaseSpec) -> None:
    flowpaths = {flowpath.label: flowpath for flowpath in spec.flowpaths}
    for valve in spec.equipment:
        flowpath = flowpaths.get(valve.flowpath)
        if flowpath is None:
            raise PydanticCustomError(
                "unknown_reference", "valve does not name a flowpath"
            )
        pipes = {pipe.label: pipe for pipe in flowpath.pipes}
        if valve.pipe not in pipes:
            raise PydanticCustomError(
                "unknown_reference", "valve pipe is not on that flowpath"
            )


def _is_connected(nodes: set[str], flowpaths: tuple[FlowpathSpec, ...]) -> bool:
    adjacent = {node: set[str]() for node in nodes}
    for flowpath in flowpaths:
        adjacent[flowpath.from_node].add(flowpath.to_node)
        adjacent[flowpath.to_node].add(flowpath.from_node)
    visited: set[str] = set()
    pending = [next(iter(nodes))]
    while pending:
        node = pending.pop()
        if node not in visited:
            visited.add(node)
            pending.extend(adjacent[node] - visited)
    return visited == nodes


def _require_shared_node_geometry(flowpaths: tuple[FlowpathSpec, ...]) -> None:
    positions: dict[str, Point] = {}
    for flowpath in flowpaths:
        endpoints = (
            (flowpath.from_node, flowpath.pipes[0].centerline_m[0]),
            (flowpath.to_node, flowpath.pipes[-1].centerline_m[-1]),
        )
        for node, point in endpoints:
            previous = positions.setdefault(node, point)
            if point_distance(previous, point) > GEOMETRY_TOLERANCE_M:
                raise PydanticCustomError(
                    "invalid_geometry", "flowpaths at a shared node must meet"
                )


def _require_verified_degrees(
    nodes: tuple[Node, ...], flowpaths: tuple[FlowpathSpec, ...], *, pass_through: bool = False
) -> None:
    # v3 also takes a one-in/one-out junction: an owner case with that JUNCTIONNODE
    # (MIXTERM in, FLOWTERM_1 out) ran to a normal stop in OLGA 2022.1.0.
    smallest = 2 if pass_through else 3
    for node in nodes:
        incoming = sum(flowpath.to_node == node.label for flowpath in flowpaths)
        outgoing = sum(flowpath.from_node == node.label for flowpath in flowpaths)
        match node:
            case SourceNode() | ClosedNode():
                valid = incoming == 0 and outgoing == 1
            case SinkNode():
                valid = incoming == 1 and outgoing == 0
            case JunctionNode():
                valid = min(incoming, outgoing) == 1 and incoming + outgoing in range(
                    smallest, 8
                )
        if not valid:
            raise PydanticCustomError(
                "invalid_topology", "node degree is outside verified v1 grammar"
            )


def _has_directed_cycle(
    nodes: tuple[Node, ...], flowpaths: tuple[FlowpathSpec, ...]
) -> bool:
    incoming = {node.label: 0 for node in nodes}
    # A list, not a set: parallel flowpaths between the same two nodes each count once.
    outgoing = {node.label: list[str]() for node in nodes}
    for flowpath in flowpaths:
        incoming[flowpath.to_node] += 1
        outgoing[flowpath.from_node].append(flowpath.to_node)
    pending = [label for label, count in incoming.items() if count == 0]
    visited = 0
    while pending:
        label = pending.pop()
        visited += 1
        for target in outgoing[label]:
            incoming[target] -= 1
            if incoming[target] == 0:
                pending.append(target)
    return visited != len(nodes)


def normalize_case_spec(raw: Mapping[str, JsonValue]) -> CaseSpec:
    """Parse model-authored JSON into the canonical frozen v1 model."""
    return CaseSpec.model_validate(dict(raw))


def case_spec_schema() -> JsonObject:
    """Return the closed model-input JSON Schema shared by all providers."""
    return CaseSpec.model_json_schema(by_alias=True)


def case_spec_inline_schema() -> JsonObject:
    """Return a reference-free schema compatible with dispatch validation."""
    return inline_case_spec_schema()


def case_spec_capabilities() -> JsonObject:
    """Return the honest, side-effect-free v2 capability matrix."""
    return capability_matrix()


def validate_case_spec(raw: Mapping[str, JsonValue]) -> CaseSpecValidationResult:
    """Return a public, structured validation result without compiling or writing."""
    legacy = legacy_version_issue(raw)
    if legacy is not None:
        return invalid_result([legacy])
    unsupported = unsupported_equipment_issue(raw)
    if unsupported is not None:
        return invalid_result([unsupported])
    try:
        normalized = normalize_case_spec(raw)
    except ValidationError as exc:
        return invalid_result(
            [validation_issue(error) for error in exc.errors(include_input=False)]
        )
    return {
        "valid": True,
        "publishable": True,
        "version": normalized.version,
        "normalized": normalized.model_dump(
            mode="json", by_alias=True, exclude_defaults=True
        ),
        "capabilities": capability_matrix(),
        "errors": [],
        "warnings": [],
    }
