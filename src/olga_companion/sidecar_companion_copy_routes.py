from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import run_companion_copy, workspace
from .agent import approvals

router = APIRouter()


class CompanionCopyRequest(BaseModel):
    source: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    tab_source: str = Field(min_length=1)
    approved: bool = False
    sha256: str | None = None
    size: int | None = None


def _facade() -> Any:
    from . import sidecar

    return sidecar


def _refused(exc: Exception) -> HTTPException:
    status = 409 if isinstance(exc, workspace.StaleWorkspaceContextError) else 400
    return HTTPException(status_code=status, detail=str(exc))


_REFUSALS = (
    run_companion_copy.RunCompanionCopyError,
    workspace.WorkspaceError,
    approvals.ApprovalError,
)


@router.post("/api/run/companion-copy/preview")
def api_companion_copy_preview(request: CompanionCopyRequest) -> dict[str, Any]:
    """Describe the exact copy for the approval prompt; writes nothing."""
    try:
        return run_companion_copy.preview(
            source=request.source, reference=request.reference, tab_source=request.tab_source
        )
    except _REFUSALS as exc:
        raise _refused(exc) from exc


@router.post("/api/run/companion-copy/execute")
def api_companion_copy_execute(
    request: CompanionCopyRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Copy the chosen table only after the user approved this exact copy."""
    _facade()._require_session_token(x_session_token)
    if not request.approved:
        raise HTTPException(status_code=400, detail="Copying a table needs the user's approval.")
    if not request.sha256 or request.size is None:
        raise HTTPException(status_code=400, detail="Copying a table needs the reviewed table's sha256 and size.")
    try:
        return run_companion_copy.approve_and_execute(
            source=request.source,
            reference=request.reference,
            tab_source=request.tab_source,
            sha256=request.sha256,
            size=request.size,
        )
    except _REFUSALS as exc:
        raise _refused(exc) from exc
