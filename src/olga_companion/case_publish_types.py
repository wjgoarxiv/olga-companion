"""Typed boundary and durable receipt values for approved case publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

HashHex = str


class _ClosedModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class PublishRequest(_ClosedModel):
    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    compiled_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    destination_rel: str = Field(min_length=8, max_length=512)
    context_generation: int = Field(ge=0)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")


class PublishApprovalBinding(_ClosedModel):
    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    compiled_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    destination_rel: str = Field(min_length=8, max_length=512)
    context_generation: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class PublishTransactionSnapshot:
    transaction_id: str
    source: Path | None
    source_hash: HashHex
    compiled: Path
    compiled_hash: HashHex
    backup: Path
    backup_hash: HashHex
    validation_clean: bool
    publishable: bool
    context_generation: int


class PublishReceipt(_ClosedModel):
    version: Literal[1] = 1
    receipt_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["completed"] = "completed"
    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    compiled_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    published_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    backup_hash: HashHex = Field(pattern=r"^[0-9a-f]{64}$")
    destination_rel: str = Field(min_length=8, max_length=512)
    context_generation: int = Field(ge=0)


class PublishJournalRecord(_ClosedModel):
    version: Literal[1] = 1
    state: Literal["intent", "completed"]
    request: PublishRequest
    receipt: PublishReceipt | None = None


@dataclass(frozen=True, slots=True)
class PublishRefusedError(RuntimeError):
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class PublishOutcomeUncertainError(RuntimeError):
    transaction_id: str

    def __str__(self) -> str:
        return (
            "The case file may have been published, but its durable receipt could "
            f"not be committed for transaction {self.transaction_id}."
        )
