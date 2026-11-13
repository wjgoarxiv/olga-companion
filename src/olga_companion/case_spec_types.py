"""Closed Pydantic value types used by CaseSpec v2."""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Annotated, ClassVar, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    model_validator,
)
from pydantic_core import PydanticCustomError

GEOMETRY_TOLERANCE_M = 1e-6
_LABEL = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_PVT_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9 ._-]{0,127}")
OUTPUT_NAMES = ("PT", "TM", "HOL", "GT", "QLT", "ID", "LIQC")
_OUTPUTS = frozenset(OUTPUT_NAMES)
# OLGA 2022.1.0 stopped with an access violation and no log for a junction labelled
# BOTTOM; the same case with the junction renamed ran to a normal stop.
RESERVED_LABELS = frozenset({"BOTTOM"})
# The toolkit reads the fluid label from `PVTTABLE LABEL=...` as `[^",\s]+`; only its
# safe subset is accepted so a label can never inject GENKEY syntax.
_FLUID_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")


def _identifier(value: str) -> str:
    canonical = value.strip().upper()
    if _LABEL.fullmatch(canonical) is None:
        raise PydanticCustomError("invalid_label", "unsafe CaseSpec label")
    if canonical in RESERVED_LABELS:
        raise PydanticCustomError("reserved_label", "OLGA cannot run with this label")
    return canonical


def _pvt_reference(value: str) -> str:
    canonical = value.strip()
    segments = canonical.split("/")
    path = PurePosixPath(canonical)
    invalid = (
        not canonical
        or "\\" in canonical
        or path.is_absolute()
        or any(segment in {"", ".", ".."} for segment in segments)
        or any(_PVT_SEGMENT.fullmatch(segment) is None for segment in segments)
        or path.suffix.lower() != ".tab"
        or len(canonical) > 240
        or any(ord(character) < 32 for character in canonical)
    )
    if invalid:
        raise PydanticCustomError(
            "invalid_pvt_reference",
            "PVT reference must be a contained relative .tab identity",
        )
    return canonical


def _fluid_label(value: str) -> str:
    canonical = value.strip()
    if _FLUID_LABEL.fullmatch(canonical) is None or _looks_numeric(canonical):
        # A numeric-looking label is what toolkit rule X010 rejects ("FLUID=1").
        raise PydanticCustomError(
            "invalid_fluid_label", "fluid label must match the PVT table label"
        )
    return canonical


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _output(value: str) -> str:
    canonical = value.strip().upper()
    if canonical not in _OUTPUTS:
        raise PydanticCustomError("unsupported_output", "output is outside CaseSpec v2")
    return canonical


Label = Annotated[StrictStr, AfterValidator(_identifier)]
PvtReference = Annotated[StrictStr, AfterValidator(_pvt_reference)]
FluidLabel = Annotated[StrictStr, AfterValidator(_fluid_label)]
OutputName = Annotated[StrictStr, AfterValidator(_output)]
CoordinateValue = Annotated[
    float, Field(strict=True, ge=-10_000_000.0, le=10_000_000.0, allow_inf_nan=False)
]
PositivePressure = Annotated[
    float, Field(strict=True, gt=0.0, le=1_000_000_000.0, allow_inf_nan=False)
]
PositiveDiameter = Annotated[
    float, Field(strict=True, gt=0.0, le=10.0, allow_inf_nan=False)
]
# Physical inputs have no defaults: the user states every value (see CaseSpec v2).
TemperatureC = Annotated[
    float, Field(strict=True, gt=-273.15, le=1_500.0, allow_inf_nan=False)
]
Roughness = Annotated[float, Field(strict=True, ge=0.0, le=0.1, allow_inf_nan=False)]
HeatTransferCoefficient = Annotated[
    float, Field(strict=True, gt=0.0, le=100_000.0, allow_inf_nan=False)
]
WallThickness = Annotated[float, Field(strict=True, gt=0.0, le=1.0, allow_inf_nan=False)]
Conductivity = Annotated[float, Field(strict=True, gt=0.0, le=1_000.0, allow_inf_nan=False)]
HeatCapacity = Annotated[float, Field(strict=True, gt=0.0, le=100_000.0, allow_inf_nan=False)]
Density = Annotated[float, Field(strict=True, gt=0.0, le=30_000.0, allow_inf_nan=False)]
SectionCount = Annotated[int, Field(strict=True, ge=1, le=5_000)]
EndTime = Annotated[
    float, Field(strict=True, gt=0.0, le=31_536_000.0, allow_inf_nan=False)
]
SourceTime = Annotated[
    float, Field(strict=True, ge=0.0, le=31_536_000.0, allow_inf_nan=False)
]
MassFlowKgS = Annotated[
    float, Field(strict=True, ge=0.0, le=1_000_000.0, allow_inf_nan=False)
]
PhaseFraction = Annotated[
    float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)
]
PipeLength = Annotated[
    float, Field(strict=True, gt=0.0, le=10_000_000.0, allow_inf_nan=False)
]
# [x, y, z] metres, compiled straight to XEND/YEND/ZEND. OLGA is Y-up: y is elevation, x and z are horizontal.
Point = tuple[CoordinateValue, CoordinateValue, CoordinateValue]


class ClosedCaseModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True
    )


class SourceNode(ClosedCaseModel):
    label: Label
    kind: Literal["source"]
    pressure_pa: PositivePressure
    temperature_c: TemperatureC
    gas_fraction: PhaseFraction
    total_water_fraction: PhaseFraction


class SinkNode(ClosedCaseModel):
    label: Label
    kind: Literal["sink"]
    pressure_pa: PositivePressure
    temperature_c: TemperatureC
    gas_fraction: PhaseFraction
    total_water_fraction: PhaseFraction


class JunctionNode(ClosedCaseModel):
    label: Label
    kind: Literal["junction"]


class ClosedNode(ClosedCaseModel):
    """No-flow boundary. Coordinates come from the attached pipe, not this node."""

    label: Label
    kind: Literal["closed"]


class InitialConditions(ClosedCaseModel):
    """One starting state for every flowpath, written as INITIALCONDITIONS with STEADYSTATE=OFF."""

    pressure_pa: PositivePressure
    temperature_c: TemperatureC
    void_fraction: PhaseFraction


class TrendPosition(ClosedCaseModel):
    """User-named observation point. The compiler places TRENDDATA here."""

    label: Label
    pipe: Label
    section: SectionCount


class ValvePoint(ClosedCaseModel):
    """One row of a v3 valve opening timetable (VALVE TIME/OPENING lists)."""

    time_s: SourceTime
    opening: PhaseFraction


class ValveEquipment(ClosedCaseModel):
    kind: Literal["valve"]
    label: Label
    flowpath: Label
    pipe: Label
    position: PhaseFraction
    diameter_m: PositiveDiameter
    opening: PhaseFraction
    # v3 only. `opening` stays the opening at the first time, so a v2 reader still sees it.
    schedule: tuple[ValvePoint, ...] | None = None

    @model_validator(mode="after")
    def schedule_times_increase(self) -> ValveEquipment:
        if self.schedule is None:
            return self
        times = [point.time_s for point in self.schedule]
        if len(times) < 2 or any(right <= left for left, right in zip(times, times[1:])):
            raise PydanticCustomError(
                "valve_schedule_not_increasing",
                "a valve schedule needs at least two increasing times",
            )
        if self.schedule[0].opening != self.opening:
            raise PydanticCustomError(
                "valve_schedule_opening_mismatch",
                "opening must equal the first scheduled opening",
            )
        return self


class MassflowPoint(ClosedCaseModel):
    """One time on a SOURCE ramp. Every column the keyword writes is required."""

    time_s: SourceTime
    mass_flow_kg_s: MassFlowKgS
    temperature_c: TemperatureC
    gas_fraction: PhaseFraction
    total_water_fraction: PhaseFraction


class MassflowSource(ClosedCaseModel):
    """Flowpath SOURCE. Every keyword on the grounded line is required."""

    label: Label
    flowpath: Label
    pipe: Label
    section: SectionCount
    time_s: SourceTime
    mass_flow_kg_s: MassFlowKgS
    temperature_c: TemperatureC
    gas_fraction: PhaseFraction
    total_water_fraction: PhaseFraction
    series: tuple[MassflowPoint, ...] | None = None

    @model_validator(mode="after")
    def series_times_increase(self) -> MassflowSource:
        if not self.series:
            return self
        if len(self.series) < 2:
            raise PydanticCustomError(
                "source_series_not_increasing",
                "a mass-flow series needs at least two increasing times",
            )
        times = [point.time_s for point in self.series]
        if any(right <= left for left, right in zip(times, times[1:])):
            raise PydanticCustomError(
                "source_series_not_increasing",
                "mass-flow series times must increase",
            )
        return self


Node = Annotated[
    SourceNode | SinkNode | JunctionNode | ClosedNode, Field(discriminator="kind")
]


class PipeSpec(ClosedCaseModel):
    label: Label
    # A pipe is either a straight centerline (v2) or a length and elevation change (v3,
    # written as OLGA LENGTH/ELEVATION with no coordinates).
    centerline_m: Annotated[tuple[Point, ...], Field(min_length=2, max_length=2)] | None = None
    length_m: PipeLength | None = None
    elevation_m: CoordinateValue | None = None
    diameter_m: PositiveDiameter
    roughness_m: Roughness
    sections: SectionCount
    segment_lengths_m: tuple[PipeLength, ...] | None = None

    @property
    def uses_length(self) -> bool:
        return self.length_m is not None

    @property
    def length(self) -> float:
        if self.length_m is not None:
            return float(self.length_m)
        assert self.centerline_m is not None
        return point_distance(self.centerline_m[0], self.centerline_m[1])

    @model_validator(mode="after")
    def require_positive_segments(self) -> PipeSpec:
        has_centerline = self.centerline_m is not None
        has_length = self.length_m is not None or self.elevation_m is not None
        if has_centerline == has_length or (has_length and None in (self.length_m, self.elevation_m)):
            raise PydanticCustomError(
                "invalid_geometry", "give a pipe either centerline_m or length_m with elevation_m"
            )
        if has_centerline and self.centerline_m[0] == self.centerline_m[1]:
            raise PydanticCustomError(
                "invalid_geometry", "centerline segments must have positive length"
            )
        if has_length and abs(float(self.elevation_m)) > float(self.length_m) + GEOMETRY_TOLERANCE_M:
            raise PydanticCustomError(
                "invalid_geometry", "a pipe cannot rise or fall more than its length"
            )
        if self.segment_lengths_m is not None:
            total = math.fsum(self.segment_lengths_m)
            if len(self.segment_lengths_m) != self.sections or not math.isclose(
                total, self.length, rel_tol=1e-6, abs_tol=GEOMETRY_TOLERANCE_M
            ):
                raise PydanticCustomError(
                    "invalid_geometry",
                    "segment_lengths_m must have one length per section and sum to the pipe length",
                )
        return self


class FlowpathSpec(ClosedCaseModel):
    label: Label
    from_node: Label = Field(alias="from")
    to_node: Label = Field(alias="to")
    pipes: Annotated[tuple[PipeSpec, ...], Field(min_length=1, max_length=500)]
    # Overrides initial_conditions.void_fraction for this flowpath only.
    initial_void_fraction: PhaseFraction | None = None

    @model_validator(mode="after")
    def require_continuous_pipes(self) -> FlowpathSpec:
        # OLGA aborts at time 0 when a flowpath has fewer than two sections in total.
        if sum(pipe.sections for pipe in self.pipes) < 2:
            raise PydanticCustomError(
                "flowpath_needs_two_sections", "OLGA needs at least two sections per flowpath"
            )
        for left, right in zip(self.pipes, self.pipes[1:]):
            if left.centerline_m is None or right.centerline_m is None:
                continue
            if (
                point_distance(left.centerline_m[-1], right.centerline_m[0])
                > GEOMETRY_TOLERANCE_M
            ):
                raise PydanticCustomError(
                    "invalid_geometry", "ordered pipe centerlines must be continuous"
                )
        return self


DEFAULT_MINDT_S = 0.001
DEFAULT_DTSTART_S = 1.0
MAX_INTERVAL_SAMPLES = 100_000


class IntegrationSpec(ClosedCaseModel):
    end_time_s: EndTime
    trend_interval_s: EndTime | None = None
    profile_interval_s: EndTime | None = None
    output_interval_s: EndTime | None = None
    max_dt_s: EndTime | None = None
    steady_state: StrictBool | None = None
    dt_start_s: EndTime | None = None
    min_dt_s: EndTime | None = None

    @model_validator(mode="after")
    def limit_stated_max_dt(self) -> IntegrationSpec:
        # A stated maximum step larger than one tenth of the end time is refused.
        # The compiler does not invent a maximum step when this field is absent.
        if self.max_dt_s is not None and self.max_dt_s > self.end_time_s / 10:
            raise PydanticCustomError(
                "max_dt_exceeds_end_fraction",
                "max_dt_s must be at most end_time_s/10",
            )
        dt_start = (
            float(self.dt_start_s) if self.dt_start_s is not None else DEFAULT_DTSTART_S
        )
        mindt = float(self.min_dt_s) if self.min_dt_s is not None else DEFAULT_MINDT_S
        if mindt > dt_start:
            raise PydanticCustomError(
                "min_dt_exceeds_dt_start",
                "min_dt_s must be at most the effective dt_start_s",
            )
        if self.max_dt_s is not None and float(self.max_dt_s) < mindt:
            raise PydanticCustomError(
                "max_dt_below_min_dt",
                "max_dt_s must be at least min_dt_s",
            )
        intervals = (
            self.trend_interval_s if self.trend_interval_s is not None else self.end_time_s / 60,
            self.profile_interval_s if self.profile_interval_s is not None else self.end_time_s / 4,
            self.output_interval_s if self.output_interval_s is not None else self.end_time_s,
        )
        for interval in intervals:
            if interval < mindt:
                raise PydanticCustomError(
                    "interval_below_min_dt",
                    "an output interval is shorter than MINDT",
                )
            if self.end_time_s / interval > MAX_INTERVAL_SAMPLES:
                raise PydanticCustomError(
                    "interval_count_exceeds_limit",
                    "an output interval asks for too many samples",
                )
        return self


class MaterialSpec(ClosedCaseModel):
    conductivity_w_mk: Conductivity
    heat_capacity_j_kgk: HeatCapacity
    density_kg_m3: Density


class WallSpec(ClosedCaseModel):
    thickness_m: WallThickness
    material: MaterialSpec


class AdiabaticThermal(ClosedCaseModel):
    """No heat exchange with the surroundings; an explicit modelling choice."""

    model: Literal["adiabatic"]


class AmbientThermal(ClosedCaseModel):
    """Heat exchange through a wall to a given ambient (HOUTEROPTION=HGIVEN)."""

    model: Literal["ambient_h_given"]
    ambient_temperature_c: TemperatureC
    outer_heat_transfer_coefficient_w_m2k: HeatTransferCoefficient
    wall: WallSpec


Thermal = Annotated[AdiabaticThermal | AmbientThermal, Field(discriminator="model")]


def point_distance(left: Point, right: Point) -> float:
    return math.dist(left, right)
