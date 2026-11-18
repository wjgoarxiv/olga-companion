from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

# The health probe runs every 20 s. Hashing every OLGA exe each time is heavy, so a found
# install is reused while the same exes keep their size and mtime. A "not found" answer is
# never reused, so a new install shows up on the next probe. Runs never use this: they
# detect and hash afresh before approval.
_CAPABILITY_TTL_S = 120.0
_capability_cache: dict[str, Any] = {}
_capability_lock = threading.Lock()


def _exe_signature(detection: dict[str, Any]) -> tuple[Any, ...] | None:
    candidates = detection.get("candidates") or []
    if not detection.get("detected") or not candidates:
        return None
    signature = []
    for item in candidates:
        try:
            stat = Path(str(item["exe"])).stat()
        except (OSError, KeyError, TypeError):
            return None
        signature.append((str(item["exe"]), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(signature))


def _settings_key(ctx: Any) -> tuple[Any, ...]:
    from . import config, runner

    try:
        manual = str(config.load_olga_exe_override())
    except Exception:  # noqa: BLE001 - a missing setting only disables reuse
        manual = "?"
    detectors = tuple(
        getattr(item, "__func__", item) for item in (ctx.detect_olga, getattr(ctx, "detect_runtime", None))
    )
    globs = tuple(str(item) for item in getattr(runner, "OLGA_EXE_GLOBS", ()) or ())
    return os.environ.get("OLGA_EXE_PATH", ""), manual, globs, detectors


def clear_capability_cache() -> None:
    with _capability_lock:
        _capability_cache.clear()


def cached_capability_detection(ctx: Any, *, now: float | None = None) -> dict[str, Any]:
    clock = time.monotonic() if now is None else now
    key = _settings_key(ctx)
    with _capability_lock:
        cached = dict(_capability_cache)
    if (
        cached
        and cached["key"] == key
        and 0 <= clock - cached["at"] < _CAPABILITY_TTL_S
        and _exe_signature(cached["value"]) == cached["signature"]
    ):
        return cached["value"]
    detection = ctx.detect_olga()
    signature = _exe_signature(detection)
    with _capability_lock:
        _capability_cache.clear()
        if signature is not None:
            _capability_cache.update({"key": key, "at": clock, "signature": signature, "value": detection})
    return detection


def run_status(ctx: Any, run_id: str) -> dict[str, Any]:
    with ctx._REGISTRY_LOCK:
        state = ctx._RUNS.get(run_id)
    if state is not None:
        return ctx._live_run_status(run_id, state)
    ctx.require_run_id(run_id)
    run_dir = ctx.sandbox_root() / "runs" / run_id
    try:
        record = ctx.load_run_record(run_dir)
    except FileNotFoundError as exc:
        raise ctx.UnknownRunError(run_id) from exc
    return ctx._status_from_receipt(record, run_dir)


def recent_runs(
    ctx: Any,
    limit: int = 20,
    source: str | None = None,
) -> list[dict[str, Any]]:
    source_path = str(Path(source).expanduser().resolve()) if source is not None else None
    records = ctx.recent_run_records(
        ctx.sandbox_root() / "runs",
        limit=limit,
        source_path=source_path,
    )
    history: list[dict[str, Any]] = []
    for record in records:
        run_dir = Path(str(record.pop("_run_dir")))
        if record.get("state") == "receipt_error":
            history.append(
                {
                    "run_id": record["run_id"],
                    "state": "receipt_error",
                    "exit_code": None,
                    "timed_out": False,
                    "cancelled": False,
                    "cancel_requested": False,
                    "ok": False,
                    "engine_failed": False,
                    "validation_valid": False,
                    "log_tail": "",
                    "run_dir": str(run_dir),
                    "command": [],
                    "detection": None,
                    "selection_id": None,
                    "outputs": [],
                    "failure": None,
                    "elapsed_ms": 0,
                    "recovered_from_receipt": False,
                    "recovery": "The persisted run receipt is invalid and cannot be recovered.",
                    "receipt_error": record["receipt_error"],
                    "solver_progress": ctx._indeterminate_solver_progress(),
                }
            )
        else:
            history.append(ctx._status_from_receipt(record, run_dir))
    return history


def run_capabilities(ctx: Any) -> dict[str, Any]:
    detection = cached_capability_detection(ctx)
    broker_check = (
        ctx.broker_capability()
        if detection.get("kind") == "engine" and not ctx._native_windows()
        else None
    )
    unsupported_native = (
        detection.get("kind") != "script"
        and str(detection.get("exe") or "").lower().endswith(".exe")
        and detection.get("kind") != "engine"
    )
    enabled = (
        bool(detection["detected"])
        and not unsupported_native
        and (broker_check is None or bool(broker_check["available"]))
    )
    if detection["detected"] and unsupported_native:
        reason = (
            "Detected native candidate is not a direct OLGA engine supported by the Explorer broker path."
        )
    elif detection["detected"] and broker_check is not None and not broker_check["available"]:
        reason = str(broker_check["reason"])
    elif detection["detected"]:
        reason = (
            f"OLGA executable detected via {detection['source']}: {detection['exe']} "
            "(availability only; runtime health is verified on each run). "
            "Runs still require validation and explicit approval."
        )
    else:
        reason = "No OLGA executable detected (checked OLGA_EXE_PATH and standard install paths)."
    return {"live_olga_run": {"enabled": enabled, "reason": reason}}
