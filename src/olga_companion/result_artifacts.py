from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Final, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .config import exports_root
from .genkey_static import OlgaInputError, file_sha256

ArtifactKind = Literal["csv", "png", "pdf"]


class ArtifactLineage(TypedDict):
    source_kind: str
    source_id: str
    source_sha256: str
    operation: str


class ArtifactReceipt(TypedDict):
    artifact_id: str
    kind: ArtifactKind
    mime: str
    size_bytes: int
    sha256: str
    suggested_filename: str
    lineage: ArtifactLineage
    workspace_generation: int
    actions: list[str]


class _StoredArtifact(TypedDict):
    receipt: ArtifactReceipt
    relative_path: str


_ARTIFACT_ID: Final = re.compile(r"^artifact_[0-9a-f]{32}$")
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_KIND_CONTRACT: Final[dict[ArtifactKind, tuple[str, str]]] = {
    "csv": (".csv", "text/csv"),
    "png": (".png", "image/png"),
    "pdf": (".pdf", "application/pdf"),
}
_ACTIONS: Final = ["download", "open_in_results", "native_save_as"]
_RECEIPT_CACHE: dict[str, ArtifactReceipt] = {}


class _ArtifactLineageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: Literal["workspace", "run"]
    source_id: str = Field(min_length=1, max_length=4096)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: Literal["results_csv", "results_plot", "report_figure"]

    @field_validator("source_id")
    @classmethod
    def source_id_is_opaque(cls, value: str) -> str:
        prefix, separator, relative = value.partition(":")
        raw_parts = relative.split("/")
        if (
            not separator
            or prefix not in {"workspace", "run"}
            or not relative
            or relative.startswith(("/", "\\"))
            or "\\" in relative
            or ":" in relative
            or any(not part for part in raw_parts)
            or any(part in {".", ".."} for part in Path(relative).parts)
            or any(ord(character) < 32 or ord(character) == 127 for character in relative)
        ):
            raise ValueError("artifact lineage source_id must be opaque")
        return value

    @model_validator(mode="after")
    def source_kind_matches_id(self) -> _ArtifactLineageModel:
        if self.source_id.partition(":")[0] != self.source_kind:
            raise ValueError("artifact lineage source kind does not match its source_id")
        return self


class _ArtifactReceiptModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    kind: ArtifactKind
    mime: Literal["text/csv", "image/png", "application/pdf"]
    size_bytes: int = Field(strict=True, ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    suggested_filename: str = Field(min_length=1, max_length=255)
    lineage: _ArtifactLineageModel
    workspace_generation: int = Field(strict=True, ge=0)
    actions: list[Literal["download", "open_in_results", "native_save_as"]]


class _StoredArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: _ArtifactReceiptModel
    relative_path: str = Field(min_length=1, max_length=4096)


def _receipt_root() -> Path:
    root = exports_root().resolve() / ".artifact-receipts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _record_path(artifact_id: str) -> Path:
    if not _ARTIFACT_ID.fullmatch(artifact_id):
        raise OlgaInputError("Invalid artifact identifier.")
    return _receipt_root() / f"{artifact_id}.json"


def _contained_export(path: Path) -> tuple[Path, str]:
    root = exports_root().resolve()
    resolved = path.expanduser().resolve()
    if root not in resolved.parents or not resolved.is_file():
        raise OlgaInputError("Artifact is not a contained export file.")
    return resolved, resolved.relative_to(root).as_posix()


def _atomic_store(path: Path, record: _StoredArtifact) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(record, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _public_receipt(model: _ArtifactReceiptModel) -> ArtifactReceipt:
    return {
        "artifact_id": model.artifact_id,
        "kind": model.kind,
        "mime": model.mime,
        "size_bytes": model.size_bytes,
        "sha256": model.sha256,
        "suggested_filename": model.suggested_filename,
        "lineage": {
            "source_kind": model.lineage.source_kind,
            "source_id": model.lineage.source_id,
            "source_sha256": model.lineage.source_sha256,
            "operation": model.lineage.operation,
        },
        "workspace_generation": model.workspace_generation,
        "actions": list(model.actions),
    }


def register(
    path: Path,
    *,
    kind: ArtifactKind,
    lineage: ArtifactLineage,
    workspace_generation: int,
) -> ArtifactReceipt:
    """Persist one path-private, hash-bound export receipt."""
    resolved, relative = _contained_export(path)
    suffix, mime = _KIND_CONTRACT[kind]
    if resolved.suffix.casefold() != suffix:
        raise OlgaInputError("Artifact extension does not match its declared format.")
    if workspace_generation < 0:
        raise OlgaInputError("Artifact workspace generation is invalid.")
    digest = file_sha256(resolved)
    artifact_id = f"artifact_{uuid.uuid4().hex}"
    try:
        model = _ArtifactReceiptModel(
            artifact_id=artifact_id,
            kind=kind,
            mime=mime,
            size_bytes=resolved.stat().st_size,
            sha256=digest,
            suggested_filename=resolved.name,
            lineage=lineage,
            workspace_generation=workspace_generation,
            actions=list(_ACTIONS),
        )
    except ValidationError as exc:
        raise OlgaInputError("Artifact receipt or lineage is invalid.") from exc
    receipt = _public_receipt(model)
    _atomic_store(
        _record_path(artifact_id),
        {"receipt": receipt, "relative_path": relative},
    )
    _RECEIPT_CACHE[artifact_id] = receipt
    return receipt


def _read_stored(artifact_id: str) -> _StoredArtifact:
    path = _record_path(artifact_id)
    try:
        model = _StoredArtifactModel.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise OlgaInputError("Artifact receipt is unavailable or invalid.") from exc
    if model.receipt.artifact_id != artifact_id:
        raise OlgaInputError("Artifact receipt is invalid.")
    expected_suffix, expected_mime = _KIND_CONTRACT[model.receipt.kind]
    if (
        model.receipt.mime != expected_mime
        or Path(model.relative_path).suffix.casefold() != expected_suffix
    ):
        raise OlgaInputError("Artifact receipt MIME or extension is invalid.")
    return {
        "receipt": _public_receipt(model.receipt),
        "relative_path": model.relative_path,
    }


def read_receipt(artifact_id: str) -> ArtifactReceipt:
    """Read the public receipt while retaining its private path server-side."""
    stored = _read_stored(artifact_id)
    receipt = stored["receipt"]
    _RECEIPT_CACHE[artifact_id] = receipt
    return receipt


def resolve(artifact_id: str) -> Path:
    """Resolve and re-verify an opaque artifact identifier for trusted routes."""
    stored = _read_stored(artifact_id)
    receipt = stored["receipt"]
    candidate, _ = _contained_export(exports_root() / stored["relative_path"])
    if candidate.name != receipt["suggested_filename"]:
        raise OlgaInputError("Artifact receipt filename is invalid.")
    if candidate.stat().st_size != receipt["size_bytes"] or file_sha256(candidate) != receipt["sha256"]:
        raise OlgaInputError("Artifact integrity changed after the receipt was issued.")
    return candidate
