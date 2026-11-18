"""Windows ReplaceFile adapter used by native Save As publication."""
from __future__ import annotations

import errno
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .native_dialog_contracts import NativeDialogError
from .native_dialog_powershell import ENCODED_REPLACE_SCRIPT, read_bounded

LocalToWindows = Callable[[Path], str]
ResolvePowerShell = Callable[[], tuple[Path | None, str]]
UseWslInit = Callable[[Path], bool]
TerminateProcess = Callable[[Any], None]


def replace_file_with_backup(
    replacement: Path,
    destination: Path,
    backup: Path,
    *,
    timeout_s: float,
    local_to_windows: LocalToWindows,
    resolve_powershell: ResolvePowerShell,
    use_wsl_init: UseWslInit,
    terminate_reap: TerminateProcess,
) -> None:
    """Use Windows ReplaceFile semantics, atomically retaining the displaced file."""
    if not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 30.0:
        raise NativeDialogError("replace timeout is out of bounds")
    if backup.exists():
        raise NativeDialogError("replace backup path must not exist")
    try:
        native_paths = {
            "OLGA_REPLACE_SOURCE": local_to_windows(replacement),
            "OLGA_REPLACE_DESTINATION": local_to_windows(destination),
            "OLGA_REPLACE_BACKUP": local_to_windows(backup),
        }
    except NativeDialogError as exc:
        raise OSError(
            errno.ENOTSUP,
            "Windows atomic replacement is unavailable",
        ) from exc
    executable, reason = resolve_powershell()
    if executable is None:
        raise OSError(errno.ENOTSUP, reason)
    bridge_through_init = use_wsl_init(executable)
    env = os.environ.copy()
    env.update(native_paths)
    if bridge_through_init:
        names = ":".join(native_paths)
        env["WSLENV"] = ":".join(filter(None, (env.get("WSLENV"), names)))
    argv = [
        *(("/init",) if bridge_through_init else ()),
        str(executable),
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        ENCODED_REPLACE_SCRIPT,
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
            process.communicate(timeout=float(timeout_s))
        except subprocess.TimeoutExpired as exc:
            terminate_reap(process)
            raise OSError(
                errno.ETIMEDOUT,
                "Windows atomic replacement timed out",
            ) from exc
        except OSError:
            raise
        if process.returncode != 0 or read_bounded(stdout_file) != b"ok":
            raise OSError(errno.EIO, "Windows atomic replacement failed")
