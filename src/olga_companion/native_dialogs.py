"""Native Windows file dialogs launched by the local Python sidecar.

The PowerShell program is fixed and encoded. Request values are bounded and
travel only through the child environment; no caller value is interpolated into
the command line or script.
"""
from __future__ import annotations

import os
import subprocess  # noqa: F401 - stable monkeypatch seam for child launches
from pathlib import Path
from typing import Any

from . import native_dialog_state as _state
from .native_dialog_contracts import (
    MAX_PATH_CHARS,  # noqa: F401 - stable facade re-export
    MAX_SUGGESTED_CHARS,  # noqa: F401 - stable facade re-export
    DialogKind,
    NativeDialogError,  # noqa: F401 - stable facade re-export
    local_to_windows,
    windows_to_local,
)
from .native_dialog_powershell import (
    ENCODED_REPLACE_SCRIPT as _ENCODED_REPLACE_SCRIPT,  # noqa: F401 - test contract
    MAX_OUTPUT_BYTES,  # noqa: F401 - stable facade re-export
    POWERSHELL_DIALOG_SCRIPT,  # noqa: F401 - stable facade re-export
    POWERSHELL_REPLACE_SCRIPT,  # noqa: F401 - stable facade re-export
    terminate_reap as _terminate_reap,
)
from .native_dialog_replace import replace_file_with_backup as _replace_file
from .native_dialog_show import show_dialog as _show_dialog
from .native_dialog_state import ContextDialogLease

MAX_TIMEOUT_SECONDS = 120.0
WSL_INTEROP_PATH = Path("/proc/sys/fs/binfmt_misc/WSLInterop")


def begin_context_dialog(
    request_id: str,
    context_generation: int,
) -> ContextDialogLease:
    """Install a newer workspace/open-case request and supersede the prior exact lease."""
    return _state.begin_context_dialog(
        request_id,
        context_generation,
        cancel_dialog,
    )


def finish_context_dialog(lease: ContextDialogLease) -> None:
    _state.finish_context_dialog(lease)


def cancel_context_dialog(request_id: str) -> bool:
    """Mark only the exact current context request cancelled; never affect its successor."""
    return _state.cancel_context_dialog(request_id)


def context_dialog_result(
    lease: ContextDialogLease,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Return an honest non-mutating result for a cancelled or superseded lease."""
    return _state.context_dialog_result(lease, result)


def apply_context_dialog(
    lease: ContextDialogLease,
    action: Any,
) -> dict[str, Any]:
    """Apply a selection only while this exact lease and workspace generation are current."""
    return _state.apply_context_dialog(lease, action)


def _powershell_candidates() -> list[str]:
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        return [
            str(
                Path(system_root)
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
        ]
    return ["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"]


def _resolve_powershell() -> tuple[Path | None, str]:
    explicit = os.environ.get("OLGA_POWERSHELL_PATH")
    candidates = [explicit] if explicit else _powershell_candidates()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path, ""
    if explicit:
        return None, "OLGA_POWERSHELL_PATH is absent or not executable"
    return None, "PowerShell executable is unavailable"


def _use_wsl_init(executable: Path) -> bool:
    return (
        os.name != "nt"
        and executable.suffix.lower() == ".exe"
        and not WSL_INTEROP_PATH.exists()
    )


def replace_file_with_backup(
    replacement: Path,
    destination: Path,
    backup: Path,
    *,
    timeout_s: float = 15.0,
) -> None:
    """Use Windows ReplaceFile semantics, atomically retaining the displaced file."""
    _replace_file(
        replacement,
        destination,
        backup,
        timeout_s=timeout_s,
        local_to_windows=local_to_windows,
        resolve_powershell=_resolve_powershell,
        use_wsl_init=_use_wsl_init,
        terminate_reap=_terminate_reap,
    )


def show_dialog(
    kind: DialogKind,
    request_id: str,
    *,
    initial_path: Path | str | None = None,
    suggested_name: str | None = None,
    timeout_s: float = MAX_TIMEOUT_SECONDS,
    context_lease: ContextDialogLease | None = None,
) -> dict[str, Any]:
    return _show_dialog(
        kind,
        request_id,
        initial_path=initial_path,
        suggested_name=suggested_name,
        timeout_s=timeout_s,
        max_timeout_s=MAX_TIMEOUT_SECONDS,
        context_lease=context_lease,
        local_to_windows=local_to_windows,
        windows_to_local=windows_to_local,
        resolve_powershell=_resolve_powershell,
        use_wsl_init=_use_wsl_init,
        terminate_reap=_terminate_reap,
    )


def cancel_dialog(request_id: str) -> dict[str, str]:
    return _state.cancel_dialog(request_id, _terminate_reap)


def active_request_ids() -> list[str]:
    return _state.active_request_ids()


def cancel_all() -> None:
    _state.cancel_all(_terminate_reap)
