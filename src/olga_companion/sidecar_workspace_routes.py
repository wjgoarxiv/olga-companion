from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from .sidecar_contracts import (
    NativeDialogCancelRequest,
    NativeOpenCaseDialogRequest,
    NativeWorkspaceDialogRequest,
    WorkspaceActiveRequest,
    WorkspaceRootRequest,
)


router = APIRouter()


def _facade() -> Any:
    from . import sidecar

    return sidecar


def selected_dialog_path(result: dict[str, Any]) -> Path | None:
    if result.get("status") != "selected":
        return None
    value = result.get("path")
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise HTTPException(
            status_code=400,
            detail="Native dialog returned an invalid path.",
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="Native dialog returned a non-absolute path.",
        )
    return path.resolve()


@router.get("/api/workspace/list")
def api_workspace_list() -> dict[str, Any]:
    snapshot = _facade().workspace.context_snapshot()
    return {
        "root": snapshot["root"],
        "cases": snapshot["cases"],
        "generation": snapshot["generation"],
    }


@router.get("/api/workspace/context")
def api_workspace_context(
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    return sidecar.workspace.context_snapshot()


@router.get("/api/workspace/active")
def api_workspace_active() -> dict[str, Any]:
    return _facade().workspace.active_workspace()


@router.post("/api/workspace/active")
def api_workspace_set_active(
    request: WorkspaceActiveRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        selection = sidecar.workspace.begin_active_selection(request.context_generation)
        return sidecar.workspace.set_active_rel(request.rel, selection=selection)
    except sidecar.workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sidecar.workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/workspace/root")
def api_workspace_set_root(
    request: WorkspaceRootRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        return sidecar.workspace.switch_root(request.path)
    except sidecar.workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/native-dialogs/workspace")
def api_native_workspace(
    request: NativeWorkspaceDialogRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        lease = sidecar.native_dialogs.begin_context_dialog(
            request.request_id,
            request.context_generation,
        )
    except sidecar.workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        result = sidecar.native_dialogs.show_dialog(
            "folder",
            request.request_id,
            initial_path=lease.context_root,
            context_lease=lease,
        )
        selected = sidecar._selected_dialog_path(result)
        if selected is None:
            return sidecar.native_dialogs.context_dialog_result(lease, result)
        if not selected.is_dir():
            raise HTTPException(
                status_code=400,
                detail="Selected workspace folder does not exist.",
            )
        try:
            return sidecar.native_dialogs.apply_context_dialog(
                lease,
                lambda: {
                    "status": "selected",
                    **sidecar.workspace.switch_root(selected),
                },
            )
        except sidecar.workspace.StaleWorkspaceContextError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sidecar.workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        sidecar.native_dialogs.finish_context_dialog(lease)


@router.post("/api/native-dialogs/open-case")
def api_native_open_case(
    request: NativeOpenCaseDialogRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        lease = sidecar.native_dialogs.begin_context_dialog(
            request.request_id,
            request.context_generation,
        )
    except sidecar.workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        result = sidecar.native_dialogs.show_dialog(
            "case-open",
            request.request_id,
            initial_path=lease.context_root,
            context_lease=lease,
        )
        selected = sidecar._selected_dialog_path(result)
        if selected is None:
            return sidecar.native_dialogs.context_dialog_result(lease, result)
        if (
            not selected.is_file()
            or selected.suffix.lower() not in sidecar.workspace.CASE_SUFFIXES
        ):
            raise HTTPException(
                status_code=400,
                detail="Selected file must be an existing .genkey or .tab case.",
            )
        try:
            return sidecar.native_dialogs.apply_context_dialog(
                lease,
                lambda: {
                    "status": "selected",
                    **sidecar.workspace.open_case_path(selected),
                },
            )
        except sidecar.workspace.StaleWorkspaceContextError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sidecar.workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        sidecar.native_dialogs.finish_context_dialog(lease)


@router.post("/api/native-dialogs/cancel")
def api_native_dialog_cancel(
    request: NativeDialogCancelRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    context_cancelled = sidecar.native_dialogs.cancel_context_dialog(request.request_id)
    result = sidecar.native_dialogs.cancel_dialog(request.request_id)
    if context_cancelled and result.get("status") == "unavailable":
        return {"status": "cancelled", "request_id": request.request_id}
    return result
