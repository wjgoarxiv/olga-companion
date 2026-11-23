"""The UI's case delete: review what will go, then the user's Approve click sends it to the Recycle Bin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from . import case_delete, workspace
from .agent import approvals
from .sidecar_contracts import CaseDeleteRequest, CaseDeleteReviewRequest

router = APIRouter()


def _facade() -> Any:
    from . import sidecar

    return sidecar


def _refused(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "refused", "message": message})


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


@router.post("/api/case-delete/review")
def api_case_delete_review(
    request: CaseDeleteReviewRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _facade()._require_session_token(x_session_token)
    try:
        return case_delete.review(request.rel)
    except (case_delete.CaseDeleteError, workspace.WorkspaceError) as exc:
        raise _refused(str(exc)) from exc
    except OSError as exc:
        raise _refused("The case file could not be read; nothing was deleted.") from exc


@router.post("/api/case-delete")
def api_case_delete(
    request: CaseDeleteRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _facade()._require_session_token(x_session_token)
    if not request.approved:
        raise _refused("Deleting a case needs your approval.")
    try:
        return case_delete.delete(request.rel, request.sha256, request.context_generation)
    except workspace.StaleWorkspaceContextError as exc:
        raise _conflict("stale_context", str(exc)) from exc
    except case_delete.StaleCaseError as exc:
        raise _conflict("stale_source", str(exc)) from exc
    except (case_delete.CaseDeleteError, workspace.WorkspaceError, approvals.ApprovalError) as exc:
        raise _refused(str(exc)) from exc
    except OSError as exc:
        raise _refused("The case file could not be moved; nothing was deleted.") from exc
