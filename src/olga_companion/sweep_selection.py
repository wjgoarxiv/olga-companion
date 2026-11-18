from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import genkey_static, runner, workspace
from .genkey_static import OlgaInputError
from .run_companions import (
    CompanionManifestEntry,
    companion_manifest,
    effective_companion_manifest,
)

MAX_SWEEP_CASES = 20
MAX_SWEEP_SPECS = 20
MAX_SWEEP_VALUES_PER_SPEC = 20
MAX_SWEEP_SPEC_CHARS = 4096


class UnknownSweepError(KeyError):
    """Raised when a sweep id is not in the preview registry."""


@dataclass(slots=True)  # noqa: RUF100  # noqa: MUTABLE_OK — run ids arrive after preview
class SweepCaseState:  # mutable registry state: run ids arrive after preview.
    index: int
    path: Path
    valid: bool
    validation_errors: list[str]
    params: list[dict[str, Any]]
    source_sha256: str
    companions: list[CompanionManifestEntry]
    run_id: str | None = None
    start_error: str | None = None
    pvt_files: list[str] = field(default_factory=list)


@dataclass(slots=True)  # noqa: RUF100  # noqa: MUTABLE_OK — execution updates lifecycle fields
class SweepState:  # mutable registry state: a preview becomes an execution.
    sweep_id: str
    base: Path
    strategy: str
    sweeps: list[str]
    timeout_s: int
    cases: list[SweepCaseState]
    output_dir: str
    command: dict[str, Any]
    detection: dict[str, Any]
    plan_id: str
    context_generation: int
    created_monotonic: float
    started_monotonic: float | None = None
    finished_monotonic: float | None = None
    cancelled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


SWEEPS: dict[str, SweepState] = {}
REGISTRY_LOCK = threading.Lock()


def approval_payload(sweep_id: str, plan_id: str) -> dict[str, str]:
    return {"sweep_id": sweep_id, "plan_id": plan_id}


def plan_id(
    base: Path,
    cases: list[SweepCaseState],
    timeout_s: int,
    detection: dict[str, Any],
    strategy: str,
    sweeps: list[str],
) -> str:
    payload = {
        "base_path": str(base.resolve()),
        "base_sha256": genkey_static.file_sha256(base),
        "base_companions": companion_manifest(base),
        "cases": [
            {
                "index": case.index,
                "path": str(case.path.resolve()),
                "sha256": genkey_static.file_sha256(case.path),
                "companions": effective_companion_manifest(case.path, base),
                "params": case.params,
            }
            for case in cases
        ],
        "timeout_s": timeout_s,
        "runtime": {
            "exe": detection.get("exe"),
            "version": detection.get("version"),
            "kind": detection.get("kind"),
            "candidate_id": detection.get("candidate_id"),
            "sha256": detection.get("sha256"),
        },
        "strategy": strategy,
        "sweeps": sweeps,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_sweep(
    base_path: str,
    sweeps: list[str],
    strategy: str,
    max_cases: int,
    timeout_s: int,
    case_factory: Callable[..., SweepCaseState] | None = None,
    plan_id_factory: Callable[..., str] | None = None,
    registry: dict[str, SweepState] | None = None,
    registry_lock: Any = None,
) -> SweepState:
    timeout_s = runner.require_timeout_seconds(timeout_s)
    case_factory = case_factory or case_from_entry
    plan_id_factory = plan_id_factory or plan_id
    registry = SWEEPS if registry is None else registry
    registry_lock = REGISTRY_LOCK if registry_lock is None else registry_lock
    _validate_request(sweeps, strategy, max_cases)
    generation = workspace.context_generation()
    with workspace.expected_context(generation):
        base = genkey_static.require_genkey_path(base_path)
        detection = runner.detect_olga(base)
        if not detection.get("detected"):
            raise OlgaInputError(
                "No suitable OLGA executable detected for the sweep base case. "
                + str(detection.get("rationale") or "")
            )
        raw = genkey_static.sweep_preview(str(base), sweeps, strategy, max_cases)
        plan = raw.get("plan")
        if not raw.get("ok") or not isinstance(plan, list):
            raise OlgaInputError("Sweep preview did not produce a valid case matrix.")
        if len(plan) > MAX_SWEEP_CASES:
            raise OlgaInputError(
                f"Sweep preview exceeded the {MAX_SWEEP_CASES}-case execution limit."
            )

        resolved_base = Path(str(raw["base"]))
        cases = [case_factory(entry, resolved_base) for entry in plan]
        resolved_strategy = str(raw["strategy"])
        resolved_sweeps = [str(spec) for spec in raw["sweeps"]]
        reviewed_plan_id = plan_id_factory(
            resolved_base,
            cases,
            timeout_s,
            detection,
            resolved_strategy,
            resolved_sweeps,
        )
        sweep_id = uuid.uuid4().hex[:12]
        state = SweepState(
            sweep_id=sweep_id,
            base=resolved_base,
            strategy=resolved_strategy,
            sweeps=resolved_sweeps,
            timeout_s=timeout_s,
            cases=cases,
            output_dir=str(raw["output_dir"]),
            command=raw["command"],
            detection=copy.deepcopy(detection),
            plan_id=reviewed_plan_id,
            context_generation=generation,
            created_monotonic=time.monotonic(),
        )
        with registry_lock:
            registry[sweep_id] = state
    return state


def get_state(
    sweep_id: str,
    registry: dict[str, SweepState] | None = None,
    registry_lock: Any = None,
) -> SweepState:
    registry = SWEEPS if registry is None else registry
    registry_lock = REGISTRY_LOCK if registry_lock is None else registry_lock
    with registry_lock:
        state = registry.get(sweep_id)
    if state is None:
        raise UnknownSweepError(sweep_id)
    if len(state.cases) > MAX_SWEEP_CASES:
        raise OlgaInputError(
            f"Sweep registry exceeds the {MAX_SWEEP_CASES}-case execution limit."
        )
    return state


def case_from_entry(entry: dict[str, Any], base: Path) -> SweepCaseState:
    path = Path(str(entry.get("path", "")))
    if not path.is_file():
        raise OlgaInputError("Sweep preview produced a missing generated case path.")
    params = entry.get("params")
    errors = entry.get("validation_errors")
    return SweepCaseState(
        index=int(entry.get("index", 0)),
        path=path,
        valid=bool(entry.get("valid")),
        validation_errors=[str(error) for error in errors]
        if isinstance(errors, list)
        else [],
        params=params if isinstance(params, list) else [],
        source_sha256=genkey_static.file_sha256(path),
        companions=effective_companion_manifest(path, base),
    )


def _validate_request(sweeps: list[str], strategy: str, max_cases: int) -> None:
    if not 1 <= max_cases <= MAX_SWEEP_CASES:
        raise OlgaInputError(f"max_cases must be between 1 and {MAX_SWEEP_CASES}.")
    if not 1 <= len(sweeps) <= MAX_SWEEP_SPECS:
        raise OlgaInputError(
            f"A sweep may contain at most {MAX_SWEEP_SPECS} specifications."
        )
    value_counts: list[int] = []
    for spec in sweeps:
        if len(spec) > MAX_SWEEP_SPEC_CHARS:
            raise OlgaInputError(
                f"Each sweep specification is limited to {MAX_SWEEP_SPEC_CHARS} characters."
            )
        values = spec.split("=", 1)[1].split(",") if "=" in spec else []
        if len(values) > MAX_SWEEP_VALUES_PER_SPEC:
            raise OlgaInputError(
                f"Each sweep specification may contain at most {MAX_SWEEP_VALUES_PER_SPEC} values."
            )
        if values:
            value_counts.append(len(values))
    requested_cases = 1
    if strategy == "cartesian":
        for count in value_counts:
            requested_cases *= count
            if requested_cases > max_cases:
                break
    else:
        requested_cases = sum(value_counts)
    if requested_cases > max_cases:
        raise OlgaInputError(
            f"Sweep request exceeds the reviewed {max_cases}-case limit."
        )
