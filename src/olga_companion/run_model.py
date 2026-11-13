from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class UnknownRunError(KeyError):
    """Raised when a run id is not in the registry."""


@dataclass(slots=True)  # noqa: RUF009  # noqa: MUTABLE_OK
class RunState:
    """Mutable lifecycle state shared by polling, reaping, and timeout threads."""

    popen: Any
    run_dir: Path
    log_path: Path
    command: list[str]
    detection: dict[str, Any]
    selection_id: str
    validation_valid: bool
    timeout_s: int
    started_monotonic: float
    timer: threading.Timer
    receipt: dict[str, Any]
    launch_strategy: str = "direct"
    broker: dict[str, Any] | None = None
    staged_case_name: str = ""
    started_wall_ns: int = 0
    finished_monotonic: float | None = None
    timed_out: bool = False
    cancelled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True, slots=True)
class PreparedRun:
    run_id: str
    run_dir: Path
    source: Path
    detection: dict[str, Any]
    launch_strategy: str
    artifact: Any | None
    staged_case_name: str
    approved_command: list[str]
    command: list[str]
    approved_source_hash: str
    staged_source_hash: str
    source_hash: str
    validation: dict[str, Any]
    companions: dict[str, Any]
    receipt: dict[str, Any]
    contained_runtime: Path | None
    execution_artifact: dict[str, str] | None
    selection_id: str
    timeout_s: int
    approved: bool
    override: bool
    working_copy: Path
