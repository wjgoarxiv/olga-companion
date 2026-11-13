from __future__ import annotations

import collections
import copy
import os
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import diagnostics, run_artifacts, run_dispatch, run_lifecycle, run_live_status, run_preflight, run_progress, run_queries, run_receipt_status, run_selection, run_status_view, run_update_gate, workspace
from .config import sandbox_root
from .genkey_static import OlgaInputError, file_sha256, require_genkey_path, run_tool
from .olga_runtime import build_command, build_display_command, default_exe_globs, detect_olga as detect_runtime
from .process_tree import terminate_process
from .run_companions import companion_manifest, expected_staged_source_sha256, staged_companions_match, stage_companions
from .run_model import RunState as _RunState
from .run_model import UnknownRunError
from .run_outputs import collect_outputs, diagnose_run_failure, log_indicates_failure as _log_indicates_failure, read_log_tail, redact_log_paths
from .run_records import RunRecordError, load_run_record, recent_run_records, require_run_id, write_run_record
from .windows_native_launch import launch_in_job, native_windows as _native_windows
from .windows_broker import BROKER_PROTOCOL, FIXED_CASE_NAME, BrokerArtifact, BrokerProcess, broker_capability, broker_heartbeat_is_live, ensure_broker, prepare_broker_run, qualify_native_completion, read_broker_status, request_broker_cancel

_DYNAMIC_DEPENDENCIES = (
    copy, os, shutil, stat, subprocess, time, uuid, diagnostics, workspace, sandbox_root,
    OlgaInputError, file_sha256, require_genkey_path, build_command, build_display_command,
    detect_runtime, terminate_process, companion_manifest, expected_staged_source_sha256,
    staged_companions_match, stage_companions, UnknownRunError, collect_outputs,
    diagnose_run_failure, _log_indicates_failure, read_log_tail, redact_log_paths, RunRecordError,
    load_run_record, recent_run_records, require_run_id, write_run_record, BROKER_PROTOCOL,
    FIXED_CASE_NAME, BrokerProcess, broker_capability, broker_heartbeat_is_live,
    ensure_broker, prepare_broker_run, qualify_native_completion, read_broker_status,
    request_broker_cancel, launch_in_job, _native_windows,
)

OLGA_EXE_GLOBS = default_exe_globs()
LOG_TAIL_CHARS = 4000
WSL_INIT_PATH = Path("/init")
WSL_INTEROP_PATH = Path("/proc/sys/fs/binfmt_misc/WSLInterop")
_RUNTIME_COPY_CHUNK_BYTES = 1024 * 1024
MAX_RUN_TIMEOUT_SECONDS = 604_800  # seven days; the Explorer broker enforces the same ceiling

_RUNS: dict[str, _RunState] = {}
_REGISTRY_LOCK = threading.Lock()
_PREPARING_SELECTION_IDS: set[str] = set()
_SELECTION_CONTEXTS: dict[str, tuple[Path, int]] = {}
_SELECTION_BOOT_NONCE = secrets.token_urlsafe(32)
_RECEIPT_RECOVERY_LOCK = threading.Lock()
_STARTING_RUNS = 0
_UPDATE_LATCHED = False
_UPDATE_LATCH_OWNER: str | None = None
_RELEASED_PREPARES: collections.deque[str] = collections.deque(maxlen=128)
_UPDATE_PREPARE_LOCK = threading.Lock()


def _context() -> Any:
    return sys.modules[__name__]


def require_timeout_seconds(value: int) -> int:
    return run_selection.require_timeout_seconds(_context(), value)


def _indeterminate_solver_progress(
    *,
    phase: str = "indeterminate",
    liveness: str = "indeterminate",
    out_name: str | None = None,
) -> dict[str, Any]:
    return run_progress.indeterminate_solver_progress(
        _context(),
        phase=phase,
        liveness=liveness,
        out_name=out_name,
    )


def _managed_progress_paths(run_dir: Path, staged_case_name: str) -> tuple[Path, Path] | None:
    return run_progress.managed_progress_paths(run_dir, staged_case_name)


def _solver_progress_for(
    run_dir: Path,
    staged_case_name: str,
    *,
    phase: str,
    liveness: str,
) -> dict[str, Any]:
    return run_progress.solver_progress_for(
        _context(), run_dir, staged_case_name, phase=phase, liveness=liveness
    )


def detect_olga(source_value: str | Path | None = None) -> dict[str, Any]:
    return run_selection.detect_olga(_context(), source_value)


def _build_command(exe: str, case_name: str) -> list[str]:
    return run_selection.build_command(_context(), exe, case_name)


def _require_detected(source_value: str | Path | None = None) -> dict[str, Any]:
    return run_selection.require_detected(_context(), source_value)


def _require_candidate(source: Path, candidate_id: str) -> dict[str, Any]:
    return run_selection.require_candidate(_context(), source, candidate_id)


def revalidate_pinned_detection(source: Path, pinned_detection: dict[str, Any]) -> dict[str, Any]:
    return run_selection.revalidate_pinned_detection(_context(), source, pinned_detection)


def _selection_id(
    source: Path,
    detection: dict[str, Any],
    timeout_s: int,
    command: list[str],
    *,
    source_sha256: str | None = None,
    companions: list[dict[str, Any]] | None = None,
    launch_strategy: str = "direct",
    broker: dict[str, Any] | None = None,
    staged_case_name: str | None = None,
) -> str:
    return run_selection.selection_id(
        _context(),
        source,
        detection,
        timeout_s,
        command,
        source_sha256=source_sha256,
        companions=companions,
        launch_strategy=launch_strategy,
        broker=broker,
        staged_case_name=staged_case_name,
    )


def selection_id_for(source: Path, detection: dict[str, Any], timeout_s: int) -> str:
    return run_selection.selection_id_for(_context(), source, detection, timeout_s)


def _launch_binding(detection: dict[str, Any]) -> tuple[str, BrokerArtifact | None, str]:
    return run_selection.launch_binding(_context(), detection)


def _validate_case(source: Path) -> dict[str, Any]:
    result = run_tool("validator", [str(source)])
    return {"valid": result.exit_code == 0, "command": result.to_dict()}


def _hash_descriptor(descriptor: int) -> str:
    return run_artifacts.hash_descriptor(_context(), descriptor)


def _contained_runtime_matches(path: Path, expected_sha256: str) -> bool:
    return run_artifacts.contained_runtime_matches(_context(), path, expected_sha256)


def _prepare_contained_runtime(
    run_dir: Path,
    detection: dict[str, Any],
) -> tuple[Path, dict[str, str]]:
    return run_artifacts.prepare_contained_runtime(_context(), run_dir, detection)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def preview_run(
    source_value: str,
    timeout_s: int = 3600,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    return run_selection.preview_run(_context(), source_value, timeout_s, candidate_id)


def execute_run(
    source_value: str,
    approved: bool = False,
    override: bool = False,
    timeout_s: int = 3600,
    selection_id: str | None = None,
    pinned_detection: dict[str, Any] | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    with starting_gate():
        return _execute_run_gated(
            source_value, approved, override, timeout_s, selection_id, pinned_detection, candidate_id
        )


def starting_gate() -> Any:
    return run_update_gate.starting_run(_context())


def begin_update_gate(owner: str) -> dict[str, Any]:
    return run_update_gate.begin_update(_context(), owner)


def release_update_gate(owner: str | None = None) -> bool:
    return run_update_gate.release(_context(), owner)


def _execute_run_gated(
    source_value: str,
    approved: bool,
    override: bool,
    timeout_s: int,
    selection_id: str | None,
    pinned_detection: dict[str, Any] | None,
    candidate_id: str | None,
) -> dict[str, Any]:
    return run_lifecycle.execute_run(
        _context(),
        source_value,
        approved=approved,
        override=override,
        timeout_s=timeout_s,
        selection_id=selection_id,
        pinned_detection=pinned_detection,
        candidate_id=candidate_id,
    )


def _execute_run_claimed(
    source_value: str,
    approved: bool = False,
    override: bool = False,
    timeout_s: int = 3600,
    selection_id: str | None = None,
    pinned_detection: dict[str, Any] | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    ctx = _context()
    prepared = run_preflight.prepare_run(
        ctx,
        source_value,
        approved=approved,
        override=override,
        timeout_s=timeout_s,
        selection_id=selection_id,
        pinned_detection=pinned_detection,
        candidate_id=candidate_id,
    )
    return run_dispatch.dispatch_prepared(ctx, prepared)


def _get_state(run_id: str) -> _RunState:
    return run_lifecycle.get_state(_context(), run_id)


def _kill(state: _RunState) -> None:
    run_lifecycle.kill(_context(), state)


def shutdown_direct_runs() -> None:
    run_lifecycle.shutdown_direct_runs(_context())


def _reap(run_id: str, state: _RunState) -> None:
    run_lifecycle.reap(_context(), run_id, state)


def _on_timeout(run_id: str) -> None:
    run_lifecycle.on_timeout(_context(), run_id)


def cancel_run(run_id: str) -> dict[str, Any]:
    return run_lifecycle.cancel_run(_context(), run_id)


def _live_run_status(run_id: str, state: _RunState) -> dict[str, Any]:
    return run_live_status.live_run_status(_context(), run_id, state)


def _reload_run_record_or(run_dir: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    return run_live_status.reload_run_record_or(_context(), run_dir, fallback)


def _status_from_receipt(record: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return run_receipt_status.status_from_receipt(_context(), record, run_dir)


def _status_from_receipt_base(
    record: dict[str, Any],
    run_dir: Path,
    state: str,
) -> dict[str, Any]:
    return run_status_view.status_from_receipt_base(_context(), record, run_dir, state)


def _receipt_cancel_requested(record: dict[str, Any], run_dir: Path) -> bool:
    return run_status_view.receipt_cancel_requested(_context(), record, run_dir)


def run_status(run_id: str) -> dict[str, Any]:
    return run_queries.run_status(_context(), run_id)


def recent_runs(limit: int = 20, source: str | None = None) -> list[dict[str, Any]]:
    return run_queries.recent_runs(_context(), limit, source)


def run_capabilities() -> dict[str, Any]:
    return run_queries.run_capabilities(_context())
