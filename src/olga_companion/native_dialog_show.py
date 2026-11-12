"""Process launch and result handling for one native dialog request."""
from __future__ import annotations

import errno
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import native_dialog_state as state
from .native_dialog_contracts import (
    MAX_SUGGESTED_CHARS,
    DialogKind,
    NativeDialogError,
    require_bounded,
    require_request_id,
)
from .native_dialog_powershell import (
    ENCODED_DIALOG_SCRIPT,
    parse_output,
    read_bounded,
)
from .native_dialog_state import ContextDialogLease

LocalToWindows = Callable[[Path | str], str]
WindowsToLocal = Callable[[str], Path]
ResolvePowerShell = Callable[[], tuple[Path | None, str]]
UseWslInit = Callable[[Path], bool]
TerminateProcess = Callable[[Any], None]


def _selected_local_path(
    kind: DialogKind,
    native_value: str,
    windows_to_local: WindowsToLocal,
) -> Path:
    local = windows_to_local(native_value).expanduser().resolve()
    if kind == "folder" and not local.is_dir():
        raise NativeDialogError("selected folder does not exist")
    if kind == "case-open" and not local.is_file():
        raise NativeDialogError("selected case file does not exist")
    if kind == "save-as" and not local.parent.is_dir():
        raise NativeDialogError("selected destination parent does not exist")
    return local


def show_dialog(
    kind: DialogKind,
    request_id: str,
    *,
    initial_path: Path | str | None,
    suggested_name: str | None,
    timeout_s: float,
    max_timeout_s: float,
    context_lease: ContextDialogLease | None,
    local_to_windows: LocalToWindows,
    windows_to_local: WindowsToLocal,
    resolve_powershell: ResolvePowerShell,
    use_wsl_init: UseWslInit,
    terminate_reap: TerminateProcess,
) -> dict[str, Any]:
    """Launch one fixed PowerShell dialog under the shared request lifecycle."""
    if kind not in ("folder", "case-open", "save-as"):
        raise NativeDialogError("unsupported dialog kind")
    require_request_id(request_id)
    if not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= max_timeout_s:
        raise NativeDialogError("dialog timeout is out of bounds")
    suggested = require_bounded(
        suggested_name,
        name="suggested name",
        limit=MAX_SUGGESTED_CHARS,
    )
    initial = ""
    if initial_path is not None:
        try:
            initial = local_to_windows(initial_path)
        except NativeDialogError as exc:
            return {"status": "unavailable", "reason": str(exc)}

    request = state.DialogRequest()
    blocked = state.register_dialog(request_id, context_lease, request)
    if blocked is not None:
        return blocked

    process: Any | None = None
    try:
        executable, reason = resolve_powershell()
        if executable is None:
            return {"status": "unavailable", "reason": reason}
        bridge_through_init = use_wsl_init(executable)
        env = os.environ.copy()
        env.update(
            {
                "OLGA_DIALOG_KIND": kind,
                "OLGA_DIALOG_INITIAL": initial,
                "OLGA_DIALOG_SUGGESTED": suggested,
            }
        )
        if bridge_through_init:
            dialog_wslenv = (
                "OLGA_DIALOG_KIND/w:OLGA_DIALOG_INITIAL/w:"
                "OLGA_DIALOG_SUGGESTED/w"
            )
            env["WSLENV"] = ":".join(
                filter(None, (env.get("WSLENV"), dialog_wslenv))
            )
        argv = [
            *(("/init",) if bridge_through_init else ()),
            str(executable),
            "-NoProfile",
            "-NonInteractive",
            "-STA",
            "-EncodedCommand",
            ENCODED_DIALOG_SCRIPT,
        ]
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=env,
                    close_fds=True,
                )
            except OSError as exc:
                if exc.errno == errno.ENOEXEC:
                    return {
                        "status": "unavailable",
                        "reason": "WSLInterop exec-format failure",
                    }
                return {
                    "status": "unavailable",
                    "reason": f"PowerShell launch failed: {exc}",
                }
            if state.bind_process(request, process):
                terminate_reap(process)
                return {"status": "cancelled"}
            try:
                process.communicate(timeout=float(timeout_s))
            except subprocess.TimeoutExpired:
                terminate_reap(process)
                return {"status": "unavailable", "reason": "timeout"}
            if state.request_cancelled(request):
                terminate_reap(process)
                return {"status": "cancelled"}
            if process.returncode != 0:
                return {
                    "status": "unavailable",
                    "reason": "PowerShell dialog process failed",
                }
            try:
                parsed = parse_output(read_bounded(stdout_file))
                if parsed["status"] == "selected":
                    selected = _selected_local_path(
                        kind,
                        parsed["path"],
                        windows_to_local,
                    )
                    return {"status": "selected", "path": str(selected)}
                return parsed
            except NativeDialogError as exc:
                return {"status": "unavailable", "reason": str(exc)}
    except BaseException:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - reap all interrupts
        if process is not None:
            terminate_reap(process)
        raise
    finally:
        state.unregister_dialog(request_id, request)
