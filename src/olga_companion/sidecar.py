from __future__ import annotations

import argparse
import logging
import os
import runpy
import shutil
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from . import __version__, native_dialogs, save_as_atomic, save_as_recovery, workspace
from .agent import (
    approval_execution,
    approvals,
    chat,
    chat_response_control,
    history,
    pending_approvals,
    session_token,
    tools,
)
from .config import APP_NAME, FRONTEND_PORT, SIDECAR_PORT, native_tab_enabled, toolkit_dir
from .diagnostics import diagnostics_capabilities
from .evaluation import EvaluationSchemaError, evaluate
from .fluids import consistency, fluid_capabilities, inspect_mfl, inspect_tab
from .flowpath_details import load_flowpath_details
from .genkey_static import (
    ALLOWED_TOPOLOGIES,
    OlgaInputError,
    capabilities,
    create_preview,
    modify_copy,
    parse_network,
    review_file,
    toolkit_status,
)
from .llm import catalog as llm_catalog
from .opc import (
    OpcGateClosedError,
    opc_capabilities,
    opc_gate_status,
    require_open_gate,
)
from .publication_plot import PublicationRendererUnavailableError
from .reports import (
    compare_cases,
    findings_report,
    generate_figure,
    markdown_report,
    stage_findings_markdown,
)
from .results import (
    export_selected_series_csv,
    extract_csv,
    load_result,
    plot_result,
    require_export_path,
    result_capabilities,
    variable_profile,
    variable_series,
)
from .run_records import RunRecordError
from .runner import (
    MAX_RUN_TIMEOUT_SECONDS,
    UnknownRunError,
    cancel_run,
    detect_olga,
    execute_run,
    preview_run,
    recent_runs,
    run_capabilities,
    run_status,
    shutdown_direct_runs,
)
from . import sidecar_contracts as _contracts
from . import sidecar_artifact_routes as _artifact_routes
from . import sidecar_core_routes as _core_routes
from . import sidecar_chat_routes as _chat_routes
from . import sidecar_native_save_routes as _native_save_routes
from . import sidecar_run_results_routes as _run_results_routes
from . import sidecar_workspace_routes as _workspace_routes
from .sidecar_local_api import (
    host_header_is_allowed as _host_header_is_allowed,
    install_local_api_guard,
    is_loopback_host as _is_loopback_host,
    lifespan as _lifespan,
    local_api_guard,
    origin_is_allowed as _origin_is_allowed,
    runtime_port as _runtime_port,
    test_transport as _test_transport,
)
from .sidecar_save_as_files import (
    SaveAsRecoveryRequiredError,
    copy_verified as _copy_verified,
    create_verified_backup as _create_verified_backup,
    private_sibling_path as _private_sibling_path,
    rename_exchange as _rename_exchange,
    replace_existing_with_prior as _replace_existing_with_prior,
    restore_attempt as _restore_attempt,
    restore_verified_backup as _restore_verified_backup,
    sha256 as _sha256,
)
from .sidecar_save_as_publish import (
    copy_export_atomic as _copy_export_atomic,
)
from .sidecar_save_as_fsync import fsync_directory as _fsync_directory
from .sidecar_save_as_restore import restore_displaced as _restore_displaced
from .case_intake import router as case_intake_router
from .sweep_routes import router as sweep_router
from .runtime_logging import LOGGER_NAME, configure_file_logging, install_request_diagnostics


CreateRequest = _contracts.CreateRequest
ReviewRequest = _contracts.ReviewRequest
ModifyCopyRequest = _contracts.ModifyCopyRequest
GenkeyTopologyRequest = _contracts.GenkeyTopologyRequest
FlowpathDetailsRequest = _contracts.FlowpathDetailsRequest
FluidPathRequest = _contracts.FluidPathRequest
RunPreviewRequest = _contracts.RunPreviewRequest
RunExecuteRequest = _contracts.RunExecuteRequest
EvaluateCriterion = _contracts.EvaluateCriterion
EvaluateRequest = _contracts.EvaluateRequest
MarkdownReportRequest = _contracts.MarkdownReportRequest
FigureRequest = _contracts.FigureRequest
CompareRequest = _contracts.CompareRequest
ResultLoadRequest = _contracts.ResultLoadRequest
ResultRangeRequest = _contracts.ResultRangeRequest
ResultExtractRequest = _contracts.ResultExtractRequest
ResultPlotRequest = _contracts.ResultPlotRequest
ResultSeriesRequest = _contracts.ResultSeriesRequest
OpcReadRequest = _contracts.OpcReadRequest
OpcWriteRequest = _contracts.OpcWriteRequest
WorkspaceActiveRequest = _contracts.WorkspaceActiveRequest
WorkspaceRootRequest = _contracts.WorkspaceRootRequest
NativeWorkspaceDialogRequest = _contracts.NativeWorkspaceDialogRequest
NativeOpenCaseDialogRequest = _contracts.NativeOpenCaseDialogRequest
NativeSaveAsDialogRequest = _contracts.NativeSaveAsDialogRequest
NativeDialogCancelRequest = _contracts.NativeDialogCancelRequest


health = _core_routes.health
api_capabilities = _core_routes.api_capabilities
topologies = _core_routes.topologies
api_create = _core_routes.api_create
api_review = _core_routes.api_review
api_genkey_topology = _core_routes.api_genkey_topology
api_modify_copy = _core_routes.api_modify_copy
api_inspect_tab = _core_routes.api_inspect_tab
api_inspect_mfl = _core_routes.api_inspect_mfl
api_fluids_consistency = _core_routes.api_fluids_consistency
api_fluids_draft_preview = _core_routes.api_fluids_draft_preview
api_fluids_open_multiflash = _core_routes.api_fluids_open_multiflash
api_fluids_pickup_tab = _core_routes.api_fluids_pickup_tab
api_evaluate = _core_routes.api_evaluate
api_reports_markdown = _core_routes.api_reports_markdown
api_reports_figure = _core_routes.api_reports_figure
api_reports_compare = _core_routes.api_reports_compare
api_opc_status = _core_routes.api_opc_status
api_opc_read = _core_routes.api_opc_read
api_opc_write = _core_routes.api_opc_write
api_run_detect = _run_results_routes.api_run_detect
api_run_preview = _run_results_routes.api_run_preview
api_run_execute = _run_results_routes.api_run_execute
api_run_status = _run_results_routes.api_run_status
api_run_history = _run_results_routes.api_run_history
api_run_cancel = _run_results_routes.api_run_cancel
api_results_load = _run_results_routes.api_results_load
api_workspace_results = _run_results_routes.api_workspace_results
_result_view_options = _run_results_routes.result_view_options
api_results_series = _run_results_routes.api_results_series
api_results_extract_csv = _run_results_routes.api_results_extract_csv
api_results_plot = _run_results_routes.api_results_plot
api_results_download = _run_results_routes.api_results_download
api_artifact_download = _artifact_routes.api_artifact_download
api_session_token = _chat_routes.api_session_token
api_providers = _chat_routes.api_providers
api_approvals_execute = _chat_routes.api_approvals_execute
api_chat_new_session = _chat_routes.api_chat_new_session
api_chat_sessions = _chat_routes.api_chat_sessions
api_chat_read_session = _chat_routes.api_chat_read_session
api_chat_delete_session = _chat_routes.api_chat_delete_session
api_chat = _chat_routes.api_chat
api_workspace_list = _workspace_routes.api_workspace_list
api_workspace_context = _workspace_routes.api_workspace_context
api_workspace_active = _workspace_routes.api_workspace_active
api_workspace_set_active = _workspace_routes.api_workspace_set_active
api_workspace_set_root = _workspace_routes.api_workspace_set_root
_selected_dialog_path = _workspace_routes.selected_dialog_path
api_native_workspace = _workspace_routes.api_native_workspace
api_native_open_case = _workspace_routes.api_native_open_case
api_native_dialog_cancel = _workspace_routes.api_native_dialog_cancel
api_native_save_as = _native_save_routes.api_native_save_as
api_native_save_as_recovery = _native_save_routes.api_native_save_as_recovery


def _require_session_token(x_session_token: str | None) -> None:
    if not session_token.verify(x_session_token):
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")


def _all_capabilities() -> dict[str, Any]:
    merged = capabilities()
    merged.update(fluid_capabilities())
    merged.update(run_capabilities())
    merged.update(result_capabilities())
    merged.update(opc_capabilities())
    merged["solver_diagnostics"] = diagnostics_capabilities()
    merged["native_tab"] = native_tab_enabled()
    return merged


def _handle(action: Any) -> Any:
    try:
        return action()
    except (
        OlgaInputError,
        PublicationRendererUnavailableError,
        workspace.WorkspaceError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _input_file(value: str, suffixes: set[str]) -> str:
    return str(workspace.resolve_input_file(value, suffixes))


def _workspace_file(value: str, suffixes: set[str]) -> str:
    path = workspace.contained(value)
    if path.name.startswith("-") or path.suffix.casefold() not in suffixes or not path.is_file():
        raise workspace.WorkspaceError("input file must be an existing workspace file with an allowed extension")
    return str(path)


def _result_file(value: str) -> str:
    return str(workspace.resolve_result(value))


app = FastAPI(title=APP_NAME, version=__version__, lifespan=_lifespan)
install_local_api_guard(app)
install_request_diagnostics(app)
app.include_router(sweep_router)
app.include_router(case_intake_router)
app.include_router(_core_routes.router)
app.include_router(_run_results_routes.router)
app.include_router(_artifact_routes.router)
app.include_router(_chat_routes.router)
app.include_router(_workspace_routes.router)
app.include_router(_native_save_routes.router)
from . import sidecar_proxy_routes as _proxy_routes  # noqa: E402

app.include_router(_proxy_routes.router)

from . import sidecar_diagnostics_routes as _diagnostics_routes  # noqa: E402

app.include_router(_diagnostics_routes.router)


def _run_packaged_tool(script_value: str, args: list[str]) -> int:
    """Run one bundled toolkit script when the frozen sidecar re-enters."""
    scripts_root = (toolkit_dir() / "scripts").resolve()
    script = Path(script_value).resolve()
    if script.parent != scripts_root or script.suffix.casefold() != ".py":
        print("Packaged toolkit script is outside the bundled allowlist.", file=sys.stderr)
        return 2
    if not script.is_file():
        print(f"Packaged toolkit script is unavailable: {script.name}", file=sys.stderr)
        return 2

    old_argv = sys.argv
    sys.path.insert(0, str(scripts_root))
    sys.argv = [str(script), *args]
    try:
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            print(str(exc.code), file=sys.stderr)
            return 1
    finally:
        sys.argv = old_argv
        sys.path.remove(str(scripts_root))
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--tool-script":
        return _run_packaged_tool(sys.argv[2], sys.argv[3:])

    parser = argparse.ArgumentParser(description="Run the OLGA Companion sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=SIDECAR_PORT, type=int)
    parser.add_argument("--frontend-port", default=FRONTEND_PORT, type=int)
    args = parser.parse_args()
    if not _is_loopback_host(args.host):
        parser.error("--host must be a loopback address (127.0.0.1, ::1, or localhost)")
    os.environ["OLGA_SIDECAR_PORT"] = str(args.port)
    os.environ["OLGA_FRONTEND_PORT"] = str(args.frontend_port)
    configure_file_logging()
    logger = logging.getLogger(LOGGER_NAME)
    logger.info("runtime_start version=%s", __version__)
    try:
        uvicorn.run(
            "olga_companion.sidecar:app",
            host=args.host,
            port=args.port,
            reload=False,
        )
    except (Exception, SystemExit) as error:
        logger.error("runtime_failed kind=%s", type(error).__name__)
        raise
    finally:
        logger.info("runtime_stop")
    return 0


_FACADE_MODULES = native_dialogs, save_as_atomic, save_as_recovery, shutil
_FACADE_AGENT = approval_execution, approvals, chat, history, pending_approvals, tools
_FACADE_GENKEY = ALLOWED_TOPOLOGIES, create_preview, load_flowpath_details, modify_copy, parse_network
_FACADE_INPUTS = review_file, toolkit_status, consistency, inspect_tab, inspect_mfl
_FACADE_EVALUATION = EvaluationSchemaError, evaluate, llm_catalog
_FACADE_OPC = OpcGateClosedError, opc_gate_status, require_open_gate
_FACADE_REPORTS = compare_cases, findings_report, generate_figure, markdown_report, stage_findings_markdown
_FACADE_RESULTS = (
    export_selected_series_csv,
    extract_csv,
    load_result,
    require_export_path,
)
_FACADE_RESULT_SEAMS = variable_series, variable_profile, plot_result
_FACADE_RUN = UnknownRunError, RunRecordError, cancel_run, execute_run, recent_runs
_FACADE_RUN_SEAMS = MAX_RUN_TIMEOUT_SECONDS, preview_run, detect_olga, run_status
_FACADE_LIFESPAN = shutdown_direct_runs, local_api_guard
_FACADE_LOCAL_API = _host_header_is_allowed, _origin_is_allowed, _runtime_port
_FACADE_TRANSPORT = (_test_transport,)
_FACADE_SAVE_AS_FILES = SaveAsRecoveryRequiredError, _copy_verified, _sha256
_FACADE_SAVE_AS_BACKUP = _create_verified_backup, _private_sibling_path
_FACADE_SAVE_AS_REPLACE = _rename_exchange, _replace_existing_with_prior
_FACADE_SAVE_AS_RESTORE = _restore_attempt, _restore_verified_backup
_FACADE_SAVE_AS_PUBLISH = _copy_export_atomic, _fsync_directory, _restore_displaced


if __name__ == "__main__":
    raise SystemExit(main())
