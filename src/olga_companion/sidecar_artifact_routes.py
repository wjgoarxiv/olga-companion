from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from . import result_artifacts
from .genkey_static import OlgaInputError


router = APIRouter()


def _facade() -> Any:
    from . import sidecar

    return sidecar


@router.get("/api/artifacts/{artifact_id}/download")
def api_artifact_download(
    artifact_id: str,
    x_session_token: str | None = Header(default=None),
) -> FileResponse:
    """Download one server-issued, integrity-checked artifact receipt."""
    _facade()._require_session_token(x_session_token)
    try:
        receipt = result_artifacts.read_receipt(artifact_id)
        path = result_artifacts.resolve(artifact_id)
    except OlgaInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=receipt["suggested_filename"],
        media_type=receipt["mime"],
    )
