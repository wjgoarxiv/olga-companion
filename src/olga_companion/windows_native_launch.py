"""Start a native OLGA engine straight from the Windows sidecar.

The installed app used to compile a helper exe into the user's AppData and start it
through Explorer. Company security software blocks or deletes such freshly built
executables (bug report 2026-11-13), so on native Windows the sidecar now starts the
engine itself with a plain CreateProcess (no suspended start, no undocumented calls).
The engine is then placed in a kill-on-close Job Object, so cancel, timeout and a
sidecar that goes away all stop the whole OLGA process tree.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any

from .runtime_logging import LOGGER_NAME

_CREATE_NO_WINDOW = 0x08000000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_DLL_DIRECTORY_LOCK = threading.Lock()


def native_windows() -> bool:
    return sys.platform == "win32"


def _kernel() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetDllDirectoryW.restype = wintypes.DWORD
    kernel32.GetDllDirectoryW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
    kernel32.SetDllDirectoryW.restype = wintypes.BOOL
    kernel32.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    return kernel32


def _kill_on_close_job(kernel32: Any) -> Any:
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _Basic),
            ("IoInfo", _Io),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(job)
        raise error
    return job


class JobProcess:
    """Popen-compatible subset; stopping it ends every process in the engine's job."""

    def __init__(self, popen: subprocess.Popen[bytes], job: Any, kernel32: Any) -> None:
        self._popen = popen
        self._job = job
        self._kernel32 = kernel32
        self._lock = threading.Lock()
        self.in_job = job is not None

    @property
    def pid(self) -> int:
        return self._popen.pid

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode

    def _release_job(self) -> None:
        with self._lock:
            if self._job is not None:
                self._kernel32.CloseHandle(self._job)
                self._job = None

    def poll(self) -> int | None:
        code = self._popen.poll()
        if code is not None:
            self._release_job()
        return code

    def wait(self, timeout: float | None = None) -> int:
        code = self._popen.wait(timeout)
        self._release_job()
        return code

    def _stop(self, exit_code: int) -> None:
        with self._lock:
            if self._job is not None:
                self._kernel32.TerminateJobObject(self._job, exit_code)
                return
        if self._popen.poll() is None:
            self._popen.kill()

    def terminate(self) -> None:
        self._stop(1223)

    def kill(self) -> None:
        self._stop(1223)


_PYTHON_ONLY = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE")


def child_environment(environ: Mapping[str, str], bundle_dir: str | None) -> dict[str, str]:
    """The sidecar's environment without anything that points into its own bundle.

    A packaged (PyInstaller) sidecar runs from a temporary _MEI folder holding its own
    DLLs; OLGA must not find them on PATH or through a variable the bundle set.
    """
    bundle = (bundle_dir or "").rstrip("\\/").casefold()

    def inside(value: str) -> bool:
        return bool(bundle) and bundle in value.casefold()

    env: dict[str, str] = {}
    for name, value in environ.items():
        upper = name.upper()
        if upper in _PYTHON_ONLY or upper.startswith(("_MEIPASS", "_PYI")):
            continue
        if upper == "PATH":
            value = ";".join(part for part in value.split(";") if part and not inside(part))
        elif inside(value):
            continue
        env[name] = value
    return env


def launch_in_job(command: list[str], *, cwd: Path, stdout: IO[bytes]) -> JobProcess:
    """Start the engine and put it in a kill-on-close job before it can do much."""
    import ctypes

    kernel32 = _kernel()
    env = child_environment(os.environ, getattr(sys, "_MEIPASS", None))
    # A PyInstaller sidecar sets its own DLL directory, and child processes inherit
    # it; OLGA must resolve its DLLs the way it does when started by hand.
    with _DLL_DIRECTORY_LOCK:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetDllDirectoryW(len(buffer), buffer)
        previous = buffer.value if length else None
        kernel32.SetDllDirectoryW(None)
        try:
            popen = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                creationflags=_CREATE_NO_WINDOW,
            )
        finally:
            kernel32.SetDllDirectoryW(previous)
    # Some managed PCs already run every program inside a job that refuses another
    # one. OLGA still runs then; stopping it ends only the engine process itself.
    try:
        job = _kill_on_close_job(kernel32)
    except OSError as exc:
        logging.getLogger(LOGGER_NAME).warning("native_job_unavailable step=create error=%s", exc)
        return JobProcess(popen, None, kernel32)
    if not kernel32.AssignProcessToJobObject(job, int(popen._handle)):  # type: ignore[attr-defined]
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        logging.getLogger(LOGGER_NAME).warning("native_job_unavailable step=assign winerror=%s", error)
        return JobProcess(popen, None, kernel32)
    return JobProcess(popen, job, kernel32)
