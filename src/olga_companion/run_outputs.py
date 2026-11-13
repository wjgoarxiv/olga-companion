from __future__ import annotations

import os
import re
import stat as stat_module
from pathlib import Path
from typing import Any, Literal, Mapping, NotRequired, Sequence, TypedDict

from .genkey_static import file_sha256
from .result_inventory import run_result_id

OUTPUT_SUFFIXES = {".out", ".tpl", ".ppl", ".rsw"}
OLGA_FAILURE_MARKERS = (
    "SIMULATION ABORTED",
    "OLGA stopped with exit message",
    "verification failed",
    "**** OLGA stopped",
    "FATAL ERROR",
)

BATCH_FAILED_RE = re.compile(r"(?im)^\s*([1-9]\d*)\s+case\(s\)\s+failed\b")
LOG_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:\\|/(?:mnt/[A-Za-z]/|home/))[^\r\n]*?[\\/]"
    r"(?P<name>[^\\/\r\n]+\.(?:genkey|tab|out|tpl|ppl|rsw|log|exe))"
)


class OutputRecord(TypedDict):
    name: str
    path: str
    suffix: str
    size: int
    mtime_ns: int
    sha256: str
    result_id: NotRequired[str]


class RunFailureDiagnostic(TypedDict):
    code: Literal[
        "opi_engine_start_failed",
        "native_communication_failure",
        "native_process_failed",
        "run_cancelled",
        "run_timed_out",
        "run_helper_failed",
        "olga_dll_load_failed",
    ]
    title: str
    detail: str
    action: str
    auto_retry_safe: bool


def log_indicates_failure(log_tail: str) -> bool:
    upper = log_tail.upper()
    return any(marker.upper() in upper for marker in OLGA_FAILURE_MARKERS) or BATCH_FAILED_RE.search(log_tail) is not None


def redact_log_paths(log_tail: str) -> str:
    """Keep operator diagnostics useful without exposing host filesystem paths."""
    return LOG_PATH_RE.sub(lambda match: match.group("name"), log_tail)


def read_log_tail(run_dir: Path, log_path: Path, limit: int) -> str:
    parts: list[str] = []
    for path in (log_path, run_dir / "BatchExecutionSummary.txt", run_dir / "BatchExecutionSummary.txt.simOut"):
        try:
            with path.open("rb") as handle:
                size = os.fstat(handle.fileno()).st_size
                offset = max(0, size - limit)
                if offset:
                    handle.seek(offset, os.SEEK_SET)
                payload = handle.read(limit)
        except OSError:
            continue
        text = payload.decode("utf-8", errors="replace")
        if offset:
            newline = text.find("\n")
            text = "" if newline < 0 else text[newline + 1 :]
        if text:
            parts.append(text)
    combined = "\n".join(parts)
    if len(combined) <= limit:
        return combined
    start = len(combined) - limit
    if combined[start - 1] != "\n":
        newline = combined.find("\n", start)
        if newline < 0:
            return ""
        start = newline + 1
    return combined[start:].lstrip("\r\n")


def diagnose_run_failure(
    *,
    exit_code: int | None,
    engine_failed: bool,
    log_tail: str,
    command: Sequence[str],
    output_count: int,
    cancelled: bool = False,
    timed_out: bool = False,
    helper_problem: str | None = None,
) -> RunFailureDiagnostic | None:
    if exit_code is None or (exit_code == 0 and not engine_failed):
        return None
    # A stop the operator or the time limit caused leaves a nonzero child exit code
    # (Windows 1223 / 1460) that says nothing about the case.
    if cancelled:
        return {
            "code": "run_cancelled",
            "title": "Run cancelled",
            "detail": f"You cancelled this run before it finished. The exit code {exit_code} comes from the cancellation, not from the case.",
            "action": "Start a new preview and approve it to run again.",
            "auto_retry_safe": False,
        }
    if timed_out:
        return {
            "code": "run_timed_out",
            "title": "Run time limit reached",
            "detail": f"The run stopped because it reached its time limit (exit code {exit_code}).",
            "action": "Raise the run time limit and run again.",
            "auto_retry_safe": False,
        }
    if helper_problem:
        return {
            "code": "run_helper_failed",
            "title": "The app's run helper stopped",
            "detail": (
                "OLGA is started through a small helper program (olga-explorer-broker.exe) "
                "that the app builds on this PC. The helper did not start or stopped "
                f"responding, so OLGA did not run the case. Reason: {helper_problem}"
            ),
            "action": (
                "1. Check whether security software blocked or removed "
                "olga-explorer-broker.exe (Windows Security > Protection history, or your "
                "company antivirus). "
                "2. Ask IT to allow the folder %LOCALAPPDATA%\\com.woojoon.olga-companion. "
                "3. Request a new preview and run again."
            ),
            "auto_retry_safe": False,
        }
    command_names = {Path(part).name.lower() for part in command}
    batch_failed = BATCH_FAILED_RE.search(log_tail) is not None
    if exit_code == 0 and engine_failed and batch_failed and "opi.exe" in command_names and output_count == 0:
        return {
            "code": "opi_engine_start_failed",
            "title": "OLGA engine did not start",
            "detail": "The OPI wrapper returned exit 0, but its batch summary reports that the case failed before producing results.",
            "action": "Check the native Windows OLGA session, simulator selection, and license/runtime health before retrying.",
            "auto_retry_safe": False,
        }
    if exit_code == 0xC0000139:
        return {
            "code": "olga_dll_load_failed",
            "title": "OLGA could not load its program files",
            "detail": (
                "OLGA stopped before it started the case (Windows code 0xC0000139: a "
                "program file it needs could not be loaded)."
            ),
            "action": (
                "1. Close OLGA Companion and start it again from the Start menu or its "
                "desktop shortcut, not from a script or another program. "
                "2. Request a new preview and run again. "
                "3. If it still fails, check that OLGA runs on its own on this PC."
            ),
            "auto_retry_safe": False,
        }
    if exit_code == 57:
        return {
            "code": "native_communication_failure",
            "title": "Native OLGA communication failed",
            "detail": "The OLGA engine returned vendor exit 57 before producing solver output.",
            "action": (
                "1. Open OLGA in the native Windows session. "
                "2. Verify runtime/service communication and license health. "
                "3. Run a small case manually, then request a new preview and explicit run."
            ),
            "auto_retry_safe": False,
        }
    return {
        "code": "native_process_failed",
        "title": "OLGA process failed",
        "detail": f"The native process returned exit {exit_code}; inspect the captured solver log for the case-specific cause.",
        "action": "Review the log and correct the reported condition before starting another run.",
        "auto_retry_safe": False,
    }


def _staged_restart_input_names(companions: Sequence[Mapping[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for entry in companions or ():
        if entry.get("kind") != "restart":
            continue
        reference = str(entry.get("reference") or "")
        resolved = str(entry.get("resolved_path") or "")
        ref = Path(reference)
        if ref.is_absolute() or ".." in ref.parts:
            name = Path(resolved).name
        elif ref.parent == Path("."):
            name = ref.name
        else:
            # Nested staged inputs are not part of this top-level inventory.
            name = ""
        if name:
            names.add(name.casefold())
    return names


def collect_outputs(
    run_dir: Path,
    *,
    companions: Sequence[Mapping[str, Any]] | None = None,
    started_wall_ns: int = 0,
) -> list[OutputRecord]:
    root = run_dir.resolve()
    restart_inputs = _staged_restart_input_names(companions)
    outputs: list[OutputRecord] = []
    for path in sorted(run_dir.iterdir(), key=lambda item: item.name.lower()):
        metadata = path.stat(follow_symlinks=False)
        if not stat_module.S_ISREG(metadata.st_mode) or path.suffix.lower() not in OUTPUT_SUFFIXES:
            continue
        if path.suffix.lower() == ".rsw" and path.name.casefold() in restart_inputs:
            continue
        resolved = path.resolve()
        if resolved.parent != root:
            continue
        stat = resolved.stat()
        record: OutputRecord = {
            "name": resolved.name,
            "path": str(resolved),
            "suffix": resolved.suffix.lower(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": file_sha256(resolved),
        }
        if resolved.suffix.lower() in {".tpl", ".ppl"}:
            record["result_id"] = run_result_id(run_dir.name, resolved.name)
        outputs.append(record)
    return outputs
