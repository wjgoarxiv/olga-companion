from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .runner import MAX_RUN_TIMEOUT_SECONDS


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    locale: str | None = None


class ChatResponseStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=12, max_length=32)


class ApprovalExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending_id: str = Field(min_length=32, max_length=32)
    session_id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    context_generation: int = Field(strict=True, ge=0)


class ApprovalRejectRequest(ApprovalExecuteRequest):
    reason: str = Field(default="", max_length=512)


class NewSessionRequest(BaseModel):
    title: str = ""


class CreateRequest(BaseModel):
    topology: str = Field(default="simple_pipeline")
    endtime_s: int = Field(default=3600, gt=0)
    pvtfile: str = Field(default="./fluid.tab", min_length=1)


class ReviewRequest(BaseModel):
    path: str = Field(min_length=1)


class ModifyCopyRequest(BaseModel):
    source: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)
    label: str | None = None


class GenkeyTopologyRequest(BaseModel):
    rel: str = Field(..., description="Workspace-relative path of the case to graph.")


class FlowpathDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rel: str = Field(min_length=1, max_length=4096)
    flowpath: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:+-]*$", max_length=256)


class FluidPathRequest(BaseModel):
    path: str = Field(min_length=1)


class FluidComponentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    mole_fraction: float = Field(ge=0.0, le=1.0)


class FluidDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fluid_label: str = Field(min_length=1, max_length=64)
    components: list[FluidComponentRequest] = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)
    temperatures: list[float] = Field(min_length=2, max_length=512)
    temperature_unit: str = Field(min_length=1, max_length=16)
    pressures: list[float] = Field(min_length=2, max_length=512)
    pressure_unit: str = Field(min_length=1, max_length=16)
    hawater: bool = False
    mfl_rel: str = Field(min_length=1, max_length=4096)
    tab_rel: str | None = Field(default=None, max_length=4096)


class FluidOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfl_path: str | None = Field(default=None, max_length=4096)
    approved: bool = False


class FluidPickupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    fluid_label: str | None = Field(default=None, max_length=64)


class RunPreviewRequest(BaseModel):
    source: str = Field(min_length=1)
    timeout_s: int = Field(default=3600, strict=True, gt=0, le=MAX_RUN_TIMEOUT_SECONDS)
    candidate_id: str | None = None


class RunExecuteRequest(BaseModel):
    source: str = Field(min_length=1)
    selection_id: str | None = None
    candidate_id: str | None = None
    approved: bool = False
    override: bool = False
    timeout_s: int = Field(default=3600, strict=True, gt=0, le=MAX_RUN_TIMEOUT_SECONDS)


class EvaluateCriterion(BaseModel):
    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class EvaluateRequest(BaseModel):
    criteria: list[EvaluateCriterion] = Field(min_length=1)


class MarkdownReportRequest(BaseModel):
    genkey: str = Field(min_length=1)
    results: str | None = None
    ppl: str | None = None
    criterion: float | None = None
    flowpath: str | None = None
    pipe: str | None = None
    title: str | None = None


class FindingsReportRequest(BaseModel):
    case_file: str = Field(min_length=1)
    results_file: str = Field(min_length=1)
    verdicts: list[dict[str, Any]] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    run_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
    )


class FigureRequest(BaseModel):
    kind: str = Field(min_length=1)
    file: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    criterion: float | None = None
    timestep: float | None = None


class CompareRequest(BaseModel):
    files: list[str] = Field(min_length=2)
    labels: list[str] | None = None
    variables: list[str] | None = None
    branch: str | None = None
    timestep: float | None = None


class ResultLoadRequest(BaseModel):
    path: str = Field(min_length=1)


class ResultRangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(default="full", min_length=1)
    fraction: float | None = None
    start: float | None = None
    end: float | None = None


class ResultExtractRequest(BaseModel):
    path: str = Field(min_length=1)
    variables: list[str] = Field(min_length=1)
    branch: str | None = None
    timestep: float | None = None
    position: str | None = Field(default=None, min_length=1)
    value_unit: str | None = Field(default=None, min_length=1, max_length=64)
    time_unit: str | None = Field(default=None, min_length=1, max_length=64)
    quantity_kind: Literal["point", "delta"] = "point"
    range: ResultRangeRequest | None = None


class ResultPlotRequest(BaseModel):
    path: str = Field(min_length=1)
    variables: list[str] | None = None
    branch: str | None = None
    position: str | None = None
    value_unit: str | None = Field(default=None, min_length=1, max_length=64)
    time_unit: str | None = Field(default=None, min_length=1, max_length=64)
    quantity_kind: Literal["point", "delta"] = "point"
    range: ResultRangeRequest | None = None


class ResultSeriesRequest(BaseModel):
    rel: str = Field(..., description="Workspace-relative path of the .tpl/.ppl file.")
    variable: str = Field(..., min_length=1)
    position: str | None = None
    value_unit: str | None = Field(default=None, min_length=1, max_length=64)
    time_unit: str | None = Field(default=None, min_length=1, max_length=64)
    quantity_kind: Literal["point", "delta"] = "point"
    range: ResultRangeRequest | None = None


class ResultProfileRequest(BaseModel):
    rel: str = Field(..., description="Workspace-relative path of the .ppl file.")
    variable: str = Field(..., min_length=1)
    branch: str = Field(..., min_length=1)
    timestep: float | None = Field(
        default=None, description="Profile time in seconds; omit for the last one."
    )


class OpcReadRequest(BaseModel):
    item: str = Field(min_length=1)


class OpcWriteRequest(BaseModel):
    item: str = Field(min_length=1)
    value: str = Field(min_length=1)
    approved: bool = False
    snapshot_id: str | None = None


class WorkspaceActiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rel: str = Field(
        strict=True,
        min_length=1,
        description="Workspace-relative path of the case to make active.",
    )
    context_generation: int = Field(strict=True, ge=0)


class WorkspaceRootRequest(BaseModel):
    path: str = Field(..., description="Directory to use as the workspace root.")


_REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class NativeWorkspaceDialogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(strict=True, pattern=_REQUEST_ID_PATTERN)
    context_generation: int = Field(strict=True, ge=0)


class NativeOpenCaseDialogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(strict=True, pattern=_REQUEST_ID_PATTERN)
    context_generation: int = Field(strict=True, ge=0)


class NativeSaveAsDialogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(strict=True, pattern=_REQUEST_ID_PATTERN)
    artifact: str = Field(strict=True, min_length=1, max_length=4096)
    initial_path: str | None = None


class NativeDialogCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(strict=True, pattern=_REQUEST_ID_PATTERN)
