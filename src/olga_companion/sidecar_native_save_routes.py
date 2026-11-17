from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from . import result_artifacts, saved_reveal
from .sidecar_contracts import NativeSaveAsDialogRequest


router = APIRouter()


def _facade() -> Any:
    from . import sidecar

    return sidecar


@router.post("/api/native-dialogs/save-as")
def api_native_save_as(
    request: NativeSaveAsDialogRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        if request.artifact.startswith("artifact:"):
            source = result_artifacts.resolve(request.artifact.removeprefix("artifact:"))
        else:
            source = sidecar.require_export_path(request.artifact)
    except sidecar.OlgaInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    start = Path(request.initial_path) if request.initial_path else None
    if start is None or not start.is_dir():
        documents = Path.home() / "Documents"
        start = documents if documents.is_dir() else source.parent
    result = sidecar.native_dialogs.show_dialog(
        "save-as",
        request.request_id,
        initial_path=start,
        suggested_name=source.name,
    )
    destination = sidecar._selected_dialog_path(result)
    if destination is None:
        return result
    try:
        size = sidecar._copy_export_atomic(source, destination)
    except sidecar.save_as_atomic.SaveAsPublishUncertainError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "message": exc.public_message,
                "instructions": (
                    "The destination was left untouched after publication. "
                    "Verify the selected file before retrying Save As."
                ),
            },
        ) from exc
    except sidecar.SaveAsRecoveryRequiredError as exc:
        try:
            recovery_id = sidecar.save_as_recovery.persist(
                exc.destination,
                exc.backup_path,
                exc.expected_hash,
            )
        except OSError:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "save_as_manual_recovery_required",
                    "message": exc.public_message,
                    "instructions": (
                        "A verified backup was retained, but its private lookup "
                        "record could not be written. Do not retry destructive changes; "
                        "contact the application administrator for manual recovery."
                    ),
                },
            ) from exc
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "message": exc.public_message,
                "recovery_id": recovery_id,
                "instructions": (
                    "Keep this recovery ID and use the authenticated recovery-status "
                    "lookup before manual recovery."
                ),
            },
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail="Save As failed safely before completion.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "selected",
        "basename": destination.name,
        "size": size,
        "reveal_id": saved_reveal.record_saved(destination),
    }


@router.get("/api/native-dialogs/save-as/recovery/{recovery_id}")
def api_native_save_as_recovery(
    recovery_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        return sidecar.save_as_recovery.status(recovery_id)
    except sidecar.save_as_recovery.RecoveryNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Recovery record not found.",
        ) from exc
