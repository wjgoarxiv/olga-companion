"""Validated broker status, cancellation, heartbeat, and completion evidence."""
from __future__ import annotations

import json
import re
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .windows_broker_protocol import (
    BROKER_PROTOCOL,
    CANCEL_NAME,
    DEFAULT_HEARTBEAT_TIMEOUT_S,
    MAX_BROKER_JSON_BYTES,
    STATUS_NAME,
    _atomic_json,
)

_UNSAFE_STATUS_MESSAGE = "Broker status is unsafe or exceeds the bounded payload limit."
_MALFORMED_STATUS_MESSAGE = "Broker status is malformed."
_STATUS_OBJECT_MESSAGE = "Broker status must be a JSON object."
_STATUS_IDENTITY_MESSAGE = "Broker status identity does not match the approved request."
_STATUS_STATE_MESSAGE = "Broker status has an invalid state."
_EXIT_CODE_MESSAGE = (
    "Terminal broker status is missing a signed 32-bit child exit code."
)
_CANCEL_ID_MESSAGE = "Broker cancellation request_id is invalid."
_CANCEL_REASON_MESSAGE = "Broker cancellation reason is invalid."

# Retry budget for reading the atomically published broker status: 10 ms doubling to
# 640 ms (about 1.3 s), longer than the broker's own one-second File.Replace retry.
_STATUS_READ_ATTEMPTS = 8
_STATUS_READ_BACKOFF_S = 0.01


def _read_status(path: Path, request_id: str) -> dict[str, Any] | None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BROKER_JSON_BYTES:
        raise ValueError(_UNSAFE_STATUS_MESSAGE)
    # The broker publishes status atomically (temp file + File.Replace), so a
    # read that fails here is the transient Windows replace/sharing window, not
    # corrupt content. Two attempts 10 ms apart could still land inside it and
    # a false "malformed" verdict kills a healthy run, so back off across a
    # wider budget before failing closed.
    for attempt in range(_STATUS_READ_ATTEMPTS):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if attempt < _STATUS_READ_ATTEMPTS - 1:
                time.sleep(_STATUS_READ_BACKOFF_S * (2**attempt))
                continue
            raise ValueError(_MALFORMED_STATUS_MESSAGE) from exc
    if not isinstance(value, dict):
        raise ValueError(_STATUS_OBJECT_MESSAGE)
    if value.get("protocol") != BROKER_PROTOCOL or value.get("request_id") != request_id:
        raise ValueError(_STATUS_IDENTITY_MESSAGE)
    if value.get("state") not in {"launching", "running", "terminal"}:
        raise ValueError(_STATUS_STATE_MESSAGE)
    if value.get("state") == "terminal":
        child_exit_code = value.get("child_exit_code")
        if (
            type(child_exit_code) is not int
            or not -(2**31) <= child_exit_code <= 2**31 - 1
        ):
            raise ValueError(_EXIT_CODE_MESSAGE)
    return value


def read_broker_status(run_dir: Path, request_id: str) -> dict[str, Any] | None:
    return _read_status(run_dir / STATUS_NAME, request_id)


def broker_heartbeat_is_live(value: Any, *, now: datetime | None = None) -> bool:
    try:
        updated = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            return False
        current = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
        age = (current - updated.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return False
    return -30 <= age <= DEFAULT_HEARTBEAT_TIMEOUT_S


def request_broker_cancel(
    run_dir: Path,
    request_id: str,
    *,
    reason: str = "cancelled",
) -> Path:
    if (
        not isinstance(request_id, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) is None
    ):
        raise ValueError(_CANCEL_ID_MESSAGE)
    if reason not in {"cancelled", "killed"}:
        raise ValueError(_CANCEL_REASON_MESSAGE)
    cancel_path = run_dir / CANCEL_NAME
    _atomic_json(
        cancel_path,
        {
            "protocol": BROKER_PROTOCOL,
            "request_id": request_id,
            "reason": reason,
            "requested_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )
    return cancel_path


def qualify_native_completion(
    run_dir: Path,
    staged_case_name: str,
    started_mtime_ns: int,
) -> dict[str, Any]:
    expected = Path(staged_case_name)
    output = run_dir / expected.with_suffix(".out").name
    try:
        metadata = output.stat(follow_symlinks=False)
        text = output.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {"ok": False, "reason": "missing_solver_out", "path": str(output)}
    except (PermissionError, OSError):
        # Windows may keep the completed file shared briefly. The runner owns
        # retry/finalization and must not convert that transient state to a
        # false missing-output terminal receipt.
        raise
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
        return {"ok": False, "reason": "empty_solver_out", "path": str(output)}
    if metadata.st_mtime_ns < started_mtime_ns:
        return {"ok": False, "reason": "stale_solver_out", "path": str(output)}
    input_match = re.search(
        r"(?im)^\s*INPUT\s+FILE\s*:\s*['\"]?([^'\"\r\n]+?)['\"]?\s*$",
        text,
    )
    input_name = (
        ""
        if input_match is None
        else input_match.group(1).strip().replace("\\", "/").rsplit("/", 1)[-1]
    )
    if input_name.casefold() != expected.name.casefold():
        return {
            "ok": False,
            "reason": "solver_out_input_mismatch",
            "path": str(output),
        }
    if re.search(r"(?im)^.*\bNORMAL\s+STOP\s+IN\s+EXECUTION\b.*$", text) is None:
        return {"ok": False, "reason": "normal_stop_missing", "path": str(output)}
    return {"ok": True, "reason": "qualified_normal_stop", "path": str(output)}


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def heartbeat_is_past(value: Any, *, now: datetime | None = None) -> bool:
    """True when the last heartbeat is older than the live window and not from the future."""
    updated = _parse_utc(value)
    if updated is None:
        return False
    current = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    return (current - updated).total_seconds() > DEFAULT_HEARTBEAT_TIMEOUT_S


def cancel_request_age_s(run_dir: Path, request_id: str, *, now: datetime | None = None) -> float | None:
    """Seconds since this request's persisted cancel was written; None when there is none."""
    path = run_dir / CANCEL_NAME
    try:
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BROKER_JSON_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("protocol") != BROKER_PROTOCOL or value.get("request_id") != request_id:
        return None
    requested = _parse_utc(value.get("requested_utc"))
    if requested is None:
        return None
    current = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    return (current - requested).total_seconds()


_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87


def broker_process_alive(pid: Any, started_utc: Any, *, platform: str | None = None) -> bool | None:
    """Whether the broker that wrote a status is still running.

    False only with proof: no process has that id, it has exited, or the id now belongs to a
    process created after the broker started (the id was reused, e.g. after a restart).
    None when this cannot be told (not Windows, access refused, unreadable times).
    """
    import sys

    if (platform or sys.platform) != "win32" or type(pid) is not int or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER else None
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        if code.value != _STILL_ACTIVE:
            return False
        started = _parse_utc(started_utc)
        times = [wintypes.FILETIME() for _ in range(4)]
        if started is None or not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return True
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        created = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
        # The broker wrote started_utc after it was created; a process born later is another one.
        return not created > started
    finally:
        kernel32.CloseHandle(handle)
