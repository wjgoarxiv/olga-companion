"""Run one ``claude -p`` turn: prompt on stdin, UTF-8 JSON lines out, whole tree ended afterwards.

The CLI's own output is always UTF-8, whatever the Windows console code page is, so the bytes
are decoded as UTF-8 here and never with the locale default. On Windows the process sits in a
kill-on-close Job Object with no console window; where a managed PC refuses the job, the tree
is ended with ``taskkill /T``. Every run is registered so app shutdown can stop it.
"""

from __future__ import annotations

import asyncio
import queue
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import process_tree, windows_native_launch
from . import claude_cli_discovery

_CHUNK = 64 * 1024
_STDERR_TAIL = 64 * 1024
_EOF = object()


@dataclass(frozen=True)
class Limits:
    first_event_s: float = 60.0
    idle_s: float = 120.0
    total_s: float = 900.0
    line_bytes: int = 8 * 1024 * 1024
    total_bytes: int = 64 * 1024 * 1024


class CliProcessError(Exception):
    """``code`` is one of ``timeout``, ``output_too_large`` or ``launch_failed``."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


_ACTIVE: set[CliProcess] = set()
_ACTIVE_LOCK = threading.Lock()


def active() -> set[CliProcess]:
    with _ACTIVE_LOCK:
        return set(_ACTIVE)


def stop_all() -> None:
    for run in active():
        run.stop()


def _windows() -> bool:
    return windows_native_launch.native_windows()


def _spawn(argv: list[str], *, env: Mapping[str, str], cwd: Path) -> Any:
    pipe = subprocess.PIPE
    if _windows():
        return windows_native_launch.launch_in_job(claude_cli_discovery.windows_command(argv), cwd=cwd, env=dict(env),
                                                   stdin=pipe, stdout=pipe,
                                                   stderr=pipe)
    return subprocess.Popen(argv, cwd=str(cwd), env=dict(env), start_new_session=True, stdin=pipe, stdout=pipe,
                            stderr=pipe)


def _kill_tree(handle: Any) -> None:
    if _windows():
        if getattr(handle, "in_job", False):
            handle.kill()
            return
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(handle.pid)], capture_output=True,
                       creationflags=0x08000000, check=False)
        if handle.poll() is None:
            handle.kill()
        return
    process_tree.terminate_process(handle, process_group_id=handle.pid)


class CliProcess:
    def __init__(self, argv: list[str], *, prompt: str, env: Mapping[str, str], cwd: Path,
                 limits: Limits | None = None) -> None:
        self._argv = list(argv)
        self._prompt = prompt.encode("utf-8")
        self._env = dict(env)
        self._cwd = Path(cwd)
        self.limits = limits or Limits()
        self._handle: Any = None
        self._lines: queue.Queue[object] = queue.Queue()
        self._stderr = bytearray()
        self._stopped = False

    @property
    def pid(self) -> int:
        return self._handle.pid if self._handle is not None else 0

    @property
    def returncode(self) -> int | None:
        return self._handle.poll() if self._handle is not None else None

    @property
    def stderr_tail(self) -> str:
        return bytes(self._stderr).decode("utf-8", errors="replace")

    def start(self) -> None:
        if self._handle is not None:
            return
        try:
            self._handle = _spawn(self._argv, env=self._env, cwd=self._cwd)
        except OSError as exc:
            raise CliProcessError("launch_failed", type(exc).__name__) from exc
        with _ACTIVE_LOCK:
            _ACTIVE.add(self)
        threading.Thread(target=self._feed_stdin, daemon=True).start()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _feed_stdin(self) -> None:
        try:
            self._handle.stdin.write(self._prompt)
            self._handle.stdin.close()
        except OSError:
            pass

    def _read_stdout(self) -> None:
        buffer = bytearray()
        total = 0
        stream = self._handle.stdout
        try:
            while chunk := stream.read1(_CHUNK) if hasattr(stream, "read1") else stream.read(_CHUNK):
                total += len(chunk)
                if total > self.limits.total_bytes:
                    self._lines.put(CliProcessError("output_too_large", "total"))
                    return
                buffer.extend(chunk)
                while (end := buffer.find(b"\n")) >= 0:
                    self._lines.put(bytes(buffer[:end]).decode("utf-8", errors="replace").rstrip("\r"))
                    del buffer[: end + 1]
                if len(buffer) > self.limits.line_bytes:
                    self._lines.put(CliProcessError("output_too_large", "line"))
                    return
            if buffer:
                self._lines.put(bytes(buffer).decode("utf-8", errors="replace").rstrip("\r"))
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(_EOF)

    def _read_stderr(self) -> None:
        try:
            while chunk := self._handle.stderr.read(_CHUNK):
                self._stderr.extend(chunk)
                if len(self._stderr) > _STDERR_TAIL:
                    del self._stderr[: len(self._stderr) - _STDERR_TAIL]
        except (OSError, ValueError):
            pass

    async def lines(self) -> AsyncIterator[str]:
        """Yield stdout lines; raise ``CliProcessError`` on a cap or timeout. Always ends the tree."""
        self.start()
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        seen = False
        try:
            while True:
                wait = self.limits.idle_s if seen else self.limits.first_event_s
                wait = min(wait, self.limits.total_s - (time.monotonic() - started))
                if wait <= 0:
                    raise CliProcessError("timeout", "total")
                try:
                    item = await asyncio.wait_for(loop.run_in_executor(None, self._lines.get, True, wait), wait + 1)
                except (queue.Empty, asyncio.TimeoutError):
                    raise CliProcessError("timeout", "idle" if seen else "first_event") from None
                if item is _EOF:
                    break
                if isinstance(item, CliProcessError):
                    raise item
                seen = True
                yield str(item)
            await loop.run_in_executor(None, self.wait, 10)
        finally:
            await asyncio.to_thread(self.stop)

    def wait(self, timeout: float | None = None) -> int | None:
        if self._handle is None:
            return None
        try:
            return self._handle.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self) -> None:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(self)
        if self._handle is None or self._stopped:
            return
        self._stopped = True
        try:
            _kill_tree(self._handle)
        except (OSError, ProcessLookupError):
            pass
        for stream in (self._handle.stdin, self._handle.stdout, self._handle.stderr):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except (OSError, ValueError):
                pass
        self.wait(5)
