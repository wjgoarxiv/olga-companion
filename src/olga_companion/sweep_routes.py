from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .agent import session_token
from . import workspace
from .genkey_static import OlgaInputError
from .runner import MAX_RUN_TIMEOUT_SECONDS
from .sweep_execution import (
    UnknownSweepError,
    cancel_sweep,
    execute_sweep,
    preview_sweep,
    sweep_status,
)
from .sweep_summary import summarize_sweep
from .sweep_parameters import discover_sweep_parameters

router = APIRouter()


class SweepPreviewRequest(BaseModel):
    base: str = Field(min_length=1)
    sweeps: list[str] = Field(min_length=1, max_length=20)
    strategy: str = "oat"
    max_cases: int = Field(default=20, gt=0, le=20)
    timeout_s: int = Field(default=3600, strict=True, gt=0, le=MAX_RUN_TIMEOUT_SECONDS)


class SweepExecuteRequest(BaseModel):
    sweep_id: str = Field(min_length=1)
    plan_id: str | None = None
    approved: bool = False


class SweepParametersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base: str = Field(min_length=1, max_length=4096)


class SweepParameterOptionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    keyword: str
    key: str


class SweepParameterCatalogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    parameters: tuple[SweepParameterOptionResponse, ...]


def _require_session_token(x_session_token: str | None) -> None:
    if not session_token.verify(x_session_token):
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")


def _handle(fn) -> dict[str, Any]:
    try:
        return fn()
    except workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OlgaInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/api/sweep/parameters",
    response_model=SweepParameterCatalogResponse,
)
def api_sweep_parameters(
    request: SweepParametersRequest,
) -> SweepParameterCatalogResponse:
    try:
        source = workspace.resolve_input_file(request.base, {".genkey"})
        parameters = discover_sweep_parameters(source)
    except workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (workspace.WorkspaceError, OlgaInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SweepParameterCatalogResponse(
        parameters=tuple(
            SweepParameterOptionResponse(
                path=parameter.path,
                keyword=parameter.keyword,
                key=parameter.key,
            )
            for parameter in parameters
        )
    )


@router.post("/api/sweep/preview")
def api_sweep_preview(request: SweepPreviewRequest) -> dict[str, Any]:
    return _handle(
        lambda: preview_sweep(
            str(workspace.resolve_input_file(request.base, {".genkey"})),
            request.sweeps,
            request.strategy,
            request.max_cases,
            request.timeout_s,
        )
    )


@router.post("/api/sweep/execute")
def api_sweep_execute(
    request: SweepExecuteRequest, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    _require_session_token(x_session_token)
    if not request.plan_id:
        raise HTTPException(
            status_code=400,
            detail="Sweep execution requires the plan_id returned by preview.",
        )
    try:
        return _handle(
            lambda: execute_sweep(request.sweep_id, request.approved, request.plan_id)
        )
    except UnknownSweepError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown sweep id: {request.sweep_id}"
        ) from exc


@router.get("/api/sweep/status/{sweep_id}")
def api_sweep_status(sweep_id: str) -> dict[str, Any]:
    try:
        return _handle(lambda: sweep_status(sweep_id))
    except UnknownSweepError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown sweep id: {sweep_id}"
        ) from exc


@router.get("/api/sweep/summary/{sweep_id}")
def api_sweep_summary(sweep_id: str) -> dict[str, Any]:
    """Read-only end-of-run table: params, run truth, key outputs per case."""
    try:
        return _handle(lambda: summarize_sweep(sweep_id))
    except UnknownSweepError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown sweep id: {sweep_id}"
        ) from exc


@router.post("/api/sweep/cancel/{sweep_id}")
def api_sweep_cancel(
    sweep_id: str, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    _require_session_token(x_session_token)
    try:
        return _handle(lambda: cancel_sweep(sweep_id))
    except UnknownSweepError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown sweep id: {sweep_id}"
        ) from exc
