from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TOOL_OUTPUT_BYTES = 8 * 1024 * 1024
TOOL_OUTPUT_LIMIT_EXIT_CODE = 125


@dataclass(frozen=True, slots=True)
class CommandResult:
    script: str
    args: list[str]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    elapsed_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "script": self.script,
            "args": self.args,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "elapsed_ms": self.elapsed_ms,
        }


class OlgaToolConfigurationError(ValueError):
    """The internal OLGA toolkit runner received an invalid configuration."""


def script_path(
    script_key: str,
    mapping: dict[str, str],
    root: Path,
    input_error: type[ValueError],
) -> Path:
    if script_key not in mapping:
        raise input_error(f"Script key is not allowlisted: {script_key}")
    path = root / "scripts" / mapping[script_key]
    if not path.exists():
        raise input_error(
            f"Required OLGA toolkit script is unavailable: {mapping[script_key]}"
        )
    return path


def toolkit_status(root: Path, mapping: dict[str, str]) -> dict[str, Any]:
    scripts = {
        name: (root / "scripts" / script).exists()
        for name, script in mapping.items()
    }
    return {
        "available": root.exists() and all(scripts.values()),
        "scripts": scripts,
    }


def tool_command(script: Path, args: list[str]) -> list[str]:
    """Return the isolated toolkit command for source and frozen runtimes."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--tool-script", str(script), *args]
    return [sys.executable, str(script), *args]


def _drain_bounded(
    stream: Any,
    limit: int,
    chunks: list[bytes],
    overflowed: threading.Event,
    process: subprocess.Popen[bytes],
) -> None:
    remaining = limit
    for chunk in iter(lambda: stream.read(64 * 1024), b""):
        kept = chunk[:remaining] if remaining else b""
        if kept:
            chunks.append(kept)
            remaining -= len(kept)
        if len(chunk) > len(kept):
            overflowed.set()
            try:
                process.kill()
            except OSError:
                pass
            break


def run_tool(
    script_key: str,
    args: list[str],
    *,
    timeout_s: int,
    mapping: dict[str, str],
    resolve_script: Callable[[str, dict[str, str]], Path],
    cwd: Path,
    max_output_bytes: int,
) -> CommandResult:
    if max_output_bytes < 1:
        raise OlgaToolConfigurationError("max_output_bytes must be positive")
    script = resolve_script(script_key, mapping)
    started = time.monotonic()
    process = subprocess.Popen(
        tool_command(script, args),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # The toolkit directory is copied into the installer verbatim, so bytecode
        # written beside those scripts ships too — and .pyc embeds the build
        # machine's absolute source path. Installed under Program Files the write
        # would fail anyway, so never emit it.
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise RuntimeError("OLGA toolkit output pipes are unavailable")
    overflowed = threading.Event()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    readers = [
        threading.Thread(
            target=_drain_bounded,
            args=(stream, max_output_bytes, chunks, overflowed, process),
            daemon=True,
        )
        for stream, chunks in (
            (process.stdout, stdout_chunks),
            (process.stderr, stderr_chunks),
        )
    ]
    for reader in readers:
        reader.start()
    try:
        exit_code = process.wait(timeout=timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = 124
        process.kill()
        process.wait()
    for reader in readers:
        reader.join()
    stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    if overflowed.is_set():
        exit_code = TOOL_OUTPUT_LIMIT_EXIT_CODE
        stderr = f"OLGA toolkit output limit exceeded ({max_output_bytes} bytes)."
    return CommandResult(
        script=mapping[script_key],
        args=args,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
