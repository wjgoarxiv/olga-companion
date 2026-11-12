from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from . import runner

from .sidecar_contracts import (
    NativeExePickDialogRequest,
    ResultExtractRequest,
    ResultLoadRequest,
    ResultPlotRequest,
    ResultProfileRequest,
    ResultSeriesRequest,
    RunExecuteRequest,
    RunPreviewRequest,
)


router = APIRouter()


def _facade() -> Any:
    from . import sidecar

    return sidecar


def result_view_options(request: Any) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if request.value_unit is not None:
        options["value_unit"] = request.value_unit
    if request.time_unit is not None:
        options["time_unit"] = request.time_unit
    if request.quantity_kind != "point":
        options["quantity_kind"] = request.quantity_kind
    if request.range is not None:
        options["range_spec"] = request.range.model_dump(exclude_none=True)
    return options


@router.get("/api/run/detect")
def api_run_detect(source: str | None = None) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: (
            sidecar.detect_olga(sidecar._input_file(source, {".genkey"}))
            if source
            else sidecar.detect_olga()
        )
    )


@router.post("/api/run/olga-exe/pick")
def api_run_olga_exe_pick(
    request: NativeExePickDialogRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        current = sidecar.detect_olga()
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — dialog still opens
        current = {}
    initial = current.get("exe") if isinstance(current, dict) else None
    try:
        initial_dir = str(Path(initial).parent) if initial else None
    except (OSError, ValueError):
        initial_dir = None
    try:
        result = sidecar.native_dialogs.show_dialog(
            "exe-pick",
            request.request_id,
            initial_path=initial_dir,
            context_lease=None,
        )
        selected = sidecar._selected_dialog_path(result)
        if selected is None:
            return result
        if not selected.is_file() or selected.suffix.lower() != ".exe":
            raise sidecar.native_dialogs.NativeDialogError(
                "Selected file must be an existing .exe executable."
            )
        from . import config as app_config

        saved = app_config.save_olga_exe_override({"exe": str(selected)})
        return {
            "status": "selected",
            "path": saved["exe"],
            "detection": sidecar.detect_olga(),
        }
    except sidecar.native_dialogs.NativeDialogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/run/olga-exe/override")
def api_run_olga_exe_clear(
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    from . import config as app_config

    try:
        cleared = app_config.clear_olga_exe_override()
    except app_config.OlgaExeOverrideError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cleared": cleared, "detection": sidecar.detect_olga()}


@router.post("/api/run/preview")
def api_run_preview(request: RunPreviewRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.preview_run(
            sidecar._input_file(request.source, {".genkey"}),
            request.timeout_s,
            request.candidate_id,
        )
    )


@router.post("/api/run/execute")
def api_run_execute(
    request: RunExecuteRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    if not request.selection_id:
        raise HTTPException(
            status_code=400,
            detail="Run execution requires the selection_id returned by preview.",
        )
    return sidecar._handle(
        lambda: sidecar.execute_run(
            sidecar._input_file(request.source, {".genkey"}),
            request.approved,
            request.override,
            request.timeout_s,
            selection_id=request.selection_id,
            candidate_id=request.candidate_id,
        )
    )


_PREPARE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _prepare_owner(value: str | None) -> str:
    if value is None or not _PREPARE_ID.fullmatch(value):
        raise HTTPException(status_code=400, detail="A valid X-Update-Prepare-Id is required.")
    return value


@router.post("/api/update/prepare")
def api_update_prepare(
    x_session_token: str | None = Header(default=None),
    x_update_prepare_id: str | None = Header(default=None),
) -> dict[str, Any]:
    """Atomically decide whether the backend may be stopped for an update."""
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    return runner.begin_update_gate(_prepare_owner(x_update_prepare_id))


@router.post("/api/update/release")
def api_update_release(
    x_session_token: str | None = Header(default=None),
    x_update_prepare_id: str | None = Header(default=None),
) -> dict[str, bool]:
    """The native side gave up or could not stop the backend: reopen launching."""
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    return {"released": runner.release_update_gate(_prepare_owner(x_update_prepare_id))}


@router.get("/api/run/status/{run_id}")
def api_run_status(run_id: str) -> dict[str, Any]:
    sidecar = _facade()
    try:
        return sidecar.run_status(run_id)
    except sidecar.UnknownRunError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown run id: {run_id}"
        ) from exc
    except sidecar.RunRecordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/run/history")
def api_run_history(limit: int = 20, source: str | None = None) -> dict[str, Any]:
    return {"runs": _facade().recent_runs(limit, source)}


@router.post("/api/run/cancel/{run_id}")
def api_run_cancel(
    run_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        return sidecar._handle(lambda: sidecar.cancel_run(run_id))
    except sidecar.UnknownRunError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown run id: {run_id}"
        ) from exc


@router.post("/api/results/load")
def api_results_load(request: ResultLoadRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(lambda: sidecar.load_result(request.path))


@router.get("/api/workspace/results")
def api_workspace_results() -> dict[str, Any]:
    return _facade().workspace.results_snapshot()


@router.post("/api/results/series")
def api_results_series(request: ResultSeriesRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.variable_series(
            request.rel,
            request.variable,
            request.position,
            **sidecar._result_view_options(request),
        )
    )


@router.post("/api/results/profile")
def api_results_profile(request: ResultProfileRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.variable_profile(
            request.rel, request.variable, request.branch, request.timestep
        )
    )


@router.post("/api/results/extract-csv")
def api_results_extract_csv(request: ResultExtractRequest) -> dict[str, Any]:
    sidecar = _facade()
    if request.position is not None:
        if len(request.variables) != 1:
            raise HTTPException(
                status_code=400,
                detail="A selected-series CSV export requires exactly one variable.",
            )
        return sidecar._handle(
            lambda: sidecar.export_selected_series_csv(
                request.path,
                request.variables[0],
                request.position,
                **sidecar._result_view_options(request),
            )
        )
    if sidecar._result_view_options(request):
        raise HTTPException(
            status_code=400,
            detail="Result view options require a selected-series CSV position.",
        )
    return sidecar._handle(
        lambda: sidecar.extract_csv(
            request.path,
            request.variables,
            request.branch,
            request.timestep,
        )
    )


@router.post("/api/results/plot")
def api_results_plot(request: ResultPlotRequest) -> dict[str, Any]:
    sidecar = _facade()
    return sidecar._handle(
        lambda: sidecar.plot_result(
            request.path,
            request.variables,
            request.branch,
            request.position,
            **sidecar._result_view_options(request),
        )
    )


@router.get("/api/results/download")
def api_results_download(path: str) -> FileResponse:
    sidecar = _facade()
    export = sidecar._handle(lambda: sidecar.require_export_path(path))
    return FileResponse(export, filename=export.name)
