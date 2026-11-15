"""Closed edit-operation grammar and immutable transaction receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from .case_spec_types import (
    ClosedCaseModel,
    EndTime,
    FluidLabel,
    Label,
    MassFlowKgS,
    OUTPUT_NAMES,
    OutputName,
    PhaseFraction,
    PositiveDiameter,
    PositivePressure,
    Roughness,
    SectionCount,
    TemperatureC,
    Thermal,
)
from .case_spec_validation import JsonObject, JsonValue


class SetIntegration(ClosedCaseModel):
    op: Literal["set_integration"]
    end_time_s: EndTime


class SetPipeGeometry(ClosedCaseModel):
    op: Literal["set_pipe_geometry"]
    flowpath: Label
    pipe: Label
    diameter_m: PositiveDiameter | None = None
    elevation_offset_m: Annotated[
        float | None,
        Field(strict=True, ge=-10_000_000.0, le=10_000_000.0, allow_inf_nan=False),
    ] = None

    @model_validator(mode="after")
    def require_change(self) -> SetPipeGeometry:
        if self.diameter_m is None and self.elevation_offset_m is None:
            raise ValueError("set_pipe_geometry requires diameter_m or elevation_offset_m")
        return self


class SetPipeSections(ClosedCaseModel):
    op: Literal["set_pipe_sections"]
    flowpath: Label
    pipe: Label
    sections: SectionCount


class SetBoundaryPressure(ClosedCaseModel):
    op: Literal["set_boundary_pressure"]
    node: Label
    pressure_pa: PositivePressure


class SetBoundaryTemperature(ClosedCaseModel):
    op: Literal["set_boundary_temperature"]
    node: Label
    temperature_c: TemperatureC


class SetPipeRoughness(ClosedCaseModel):
    op: Literal["set_pipe_roughness"]
    flowpath: Label
    pipe: Label
    roughness_m: Roughness


class SetThermal(ClosedCaseModel):
    op: Literal["set_thermal"]
    thermal: Thermal


class SetFluid(ClosedCaseModel):
    op: Literal["set_fluid"]
    fluid_label: FluidLabel


class SetOutputs(ClosedCaseModel):
    op: Literal["set_outputs"]
    outputs: Annotated[
        tuple[OutputName, ...], Field(min_length=1, max_length=len(OUTPUT_NAMES))
    ]

    @model_validator(mode="after")
    def require_unique_outputs(self) -> SetOutputs:
        if len(set(self.outputs)) != len(self.outputs):
            raise ValueError("outputs must be unique")
        return self


class RenameNode(ClosedCaseModel):
    op: Literal["rename_node"]
    node: Label
    new_label: Label


class SetSourceMassflow(ClosedCaseModel):
    """Change a recovered SOURCE. Omitted companions stay on that source."""

    op: Literal["set_source_massflow"]
    label: Label
    mass_flow_kg_s: MassFlowKgS
    temperature_c: TemperatureC | None = None
    gas_fraction: PhaseFraction | None = None
    total_water_fraction: PhaseFraction | None = None


class SetValveOpening(ClosedCaseModel):
    op: Literal["set_valve_opening"]
    label: Label
    opening: PhaseFraction


EditOperation: TypeAlias = Annotated[
    SetIntegration
    | SetPipeGeometry
    | SetPipeSections
    | SetBoundaryPressure
    | SetBoundaryTemperature
    | SetPipeRoughness
    | SetThermal
    | SetFluid
    | SetOutputs
    | RenameNode
    | SetSourceMassflow
    | SetValveOpening,
    Field(discriminator="op"),
]
_OPERATION_ADAPTER: TypeAdapter[EditOperation] = TypeAdapter(EditOperation)


def parse_operation(raw: JsonObject) -> EditOperation:
    """Parse one model-authored operation through the closed grammar."""
    return _OPERATION_ADAPTER.validate_python(raw)


@dataclass(frozen=True, slots=True)
class TransactionIssue:
    code: str
    message: str
    evidence: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    index: int
    spec_hash: str
    previous_hash: str | None


@dataclass(frozen=True, slots=True)
class SemanticDiff:
    path: str
    before: JsonValue
    after: JsonValue


@dataclass(frozen=True, slots=True)
class BackupReceipt:
    available: bool
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    clean: bool
    parser_clean: bool
    validator_clean: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    available: bool
    restore_hash: str
    source_unchanged: bool


@dataclass(frozen=True, slots=True)
class TransactionPlan:
    transaction_id: str
    transaction_hash: str
    source_hash: str
    working_hash: str
    compiled_hash: str
    compiled_bytes: bytes
    snapshots: tuple[Snapshot, ...]
    semantic_diff: tuple[SemanticDiff, ...]
    text_diff: tuple[str, ...]
    backup: BackupReceipt
    validation: ValidationReceipt
    rollback: RollbackReceipt
    publishable: Literal[True] = True
    source_mutated: Literal[False] = False


@dataclass(frozen=True, slots=True)
class TransactionFailure:
    transaction_id: str
    source_hash: str
    snapshots: tuple[Snapshot, ...]
    failed_step: int
    errors: tuple[TransactionIssue, ...]
    publishable: Literal[False] = False
    source_mutated: Literal[False] = False


TransactionResult: TypeAlias = TransactionPlan | TransactionFailure
OperationValidationError = ValidationError
