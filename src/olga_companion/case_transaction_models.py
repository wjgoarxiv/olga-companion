"""Closed edit-operation grammar and immutable transaction receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from .case_spec_types import (
    ClosedCaseModel,
    Conductivity,
    ControllerGain,
    ControllerSeconds,
    ControllerSignal,
    IntegralSeconds,
    Density,
    EndTime,
    HeatCapacity,
    HeatTransferCoefficient,
    WallThickness,
    FluidLabel,
    Label,
    MassFlowKgS,
    OUTPUT_NAMES,
    OutputName,
    PhaseFraction,
    PipeLength,
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


class SetTimeStep(ClosedCaseModel):
    """Time-step limits and output intervals; the whole-case rules (MINDT at most DTSTART and
    MAXDT, MAXDT at most ENDTIME/10, intervals at least MINDT) run when the plan is validated."""

    op: Literal["set_time_step"]
    max_dt_s: EndTime | None = None
    min_dt_s: EndTime | None = None
    dt_start_s: EndTime | None = None
    trend_interval_s: EndTime | None = None
    profile_interval_s: EndTime | None = None
    output_interval_s: EndTime | None = None

    @model_validator(mode="after")
    def require_change(self) -> SetTimeStep:
        if all(getattr(self, name) is None for name in TIME_STEP_FIELDS):
            raise ValueError("set_time_step requires at least one value")
        return self


TIME_STEP_FIELDS: Final = (
    "max_dt_s", "min_dt_s", "dt_start_s", "trend_interval_s", "profile_interval_s", "output_interval_s",
)


class SetThermalValue(ClosedCaseModel):
    """One or more values of an ambient heat-transfer model; the model itself (adiabatic or
    ambient) is not changed here, so an adiabatic case refuses it."""

    op: Literal["set_thermal_value"]
    ambient_temperature_c: TemperatureC | None = None
    outer_heat_transfer_coefficient_w_m2k: HeatTransferCoefficient | None = None
    wall_thickness_m: WallThickness | None = None
    wall_conductivity_w_mk: Conductivity | None = None
    wall_heat_capacity_j_kgk: HeatCapacity | None = None
    wall_density_kg_m3: Density | None = None

    @model_validator(mode="after")
    def require_change(self) -> SetThermalValue:
        if all(getattr(self, name) is None for name in THERMAL_VALUE_FIELDS):
            raise ValueError("set_thermal_value requires at least one value")
        return self


THERMAL_VALUE_FIELDS: Final = (
    "ambient_temperature_c", "outer_heat_transfer_coefficient_w_m2k", "wall_thickness_m",
    "wall_conductivity_w_mk", "wall_heat_capacity_j_kgk", "wall_density_kg_m3",
)


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


class SetPipeLength(ClosedCaseModel):
    """New length of one pipe; its sections scale with it and later pipes move with its end."""

    op: Literal["set_pipe_length"]
    flowpath: Label
    pipe: Label
    length_m: PipeLength


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


CONTROLLER_VALUE_FIELDS: Final = ("setpoint", "gain", "integral_s", "derivative_s")


class SetControllerValue(ClosedCaseModel):
    """One or more tuning values of one PID loop (0.1.21); what it measures and drives stays."""

    op: Literal["set_controller_value"]
    label: Label
    setpoint: ControllerSignal | None = None
    gain: ControllerGain | None = None
    integral_s: IntegralSeconds | None = None
    derivative_s: ControllerSeconds | None = None

    @model_validator(mode="after")
    def require_change(self) -> SetControllerValue:
        if all(getattr(self, name) is None for name in CONTROLLER_VALUE_FIELDS):
            raise ValueError("set_controller_value requires at least one value")
        return self


EditOperation: TypeAlias = Annotated[
    SetIntegration
    | SetTimeStep
    | SetThermalValue
    | SetPipeGeometry
    | SetPipeSections
    | SetPipeLength
    | SetBoundaryPressure
    | SetBoundaryTemperature
    | SetPipeRoughness
    | SetThermal
    | SetFluid
    | SetOutputs
    | RenameNode
    | SetSourceMassflow
    | SetValveOpening
    | SetControllerValue,
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
    warnings: tuple[str, ...] = ()
    warning_count: int = 0


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
