"""Closed request and evidence types for simulation preflight."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HashHex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{7,127}$")]


class _ClosedModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class ActiveCaseBinding(_ClosedModel):
    kind: Literal["active_case"] = "active_case"
    source_sha256: HashHex


class TransactionBinding(_ClosedModel):
    kind: Literal["transaction"] = "transaction"
    transaction_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    source_sha256: HashHex
    compiled_sha256: HashHex


CaseBinding = Annotated[
    ActiveCaseBinding | TransactionBinding,
    Field(discriminator="kind"),
]


class IntegrationSettings(_ClosedModel):
    end_time_s: int = Field(strict=True, ge=1, le=31_536_000)


class RuntimeSelection(_ClosedModel):
    candidate_id: OpaqueId
    runtime_id: OpaqueId


class OutputTarget(_ClosedModel):
    relative_dir: str = Field(min_length=1, max_length=240)

    @field_validator("relative_dir")
    @classmethod
    def require_contained_relative_dir(cls, value: str) -> str:
        path = PurePosixPath(value)
        forbidden = path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts)
        if forbidden or "\\" in value or ":" in value:
            msg = "output target must be a contained POSIX-relative directory"
            raise ValueError(msg)
        return value


class SimulationSetup(_ClosedModel):
    binding: CaseBinding
    integration: IntegrationSettings
    outputs: tuple[str, ...] = Field(min_length=1, max_length=32)
    runtime: RuntimeSelection
    timeout_s: int = Field(strict=True, ge=1, le=604_800)
    output_target: OutputTarget
    context_generation: int = Field(strict=True, ge=0)

    @field_validator("outputs")
    @classmethod
    def require_output_identifiers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            msg = "outputs must be unique"
            raise ValueError(msg)
        if any(re.fullmatch(r"[A-Z][A-Z0-9_.]{0,31}", value) is None for value in values):
            msg = "outputs must be uppercase OLGA variable identifiers"
            raise ValueError(msg)
        return values


@dataclass(frozen=True, slots=True)
class CaseReviewEvidence:
    valid: bool
    certain: bool
    source_sha256: str
    compiled_sha256: str | None
    configured_end_time_s: float
    configured_outputs: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FluidEvidence:
    consistent: bool
    certain: bool
    run_input_sha256: str
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    available: bool
    certainty: Literal["certain", "uncertain"]
    candidate_id: str
    runtime_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class PreviewEvidence:
    ready: bool
    setup_hash: str
    run_input_sha256: str
    candidate_id: str
    runtime_id: str
    timeout_s: int
    context_generation: int
    selection_id: str
    command_label: str
    errors: tuple[str, ...]


class PreflightApproved(_ClosedModel):
    ready: Literal[True] = True
    setup_hash: HashHex
    run_input_sha256: HashHex
    selection_id: OpaqueId
    context_generation: int = Field(ge=0)
    receipt: str = Field(min_length=1, max_length=1000)


class PreflightRefused(_ClosedModel):
    ready: Literal[False] = False
    setup_hash: HashHex
    reason: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    receipt: str = Field(min_length=1, max_length=1000)


PreflightResult = PreflightApproved | PreflightRefused
