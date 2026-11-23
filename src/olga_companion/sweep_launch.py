from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from . import genkey_static, runner, workspace
from .genkey_static import OlgaInputError
from .run_companions import (
    companion_manifest,
    effective_companion_manifest,
    expected_staged_source_sha256,
    staged_companions_match,
    stage_companions,
)
from .sweep_selection import MAX_SWEEP_CASES, SweepState, plan_id

MaterializeCompanions = Callable[[Path, Path], list[str]]
PlanIdFactory = Callable[..., str]


def launch_sweep(
    state: SweepState,
    plan_id_value: str | None,
    materialize_companions: MaterializeCompanions,
    plan_id_factory: PlanIdFactory = plan_id,
) -> None:
    # Child launches are sequential: between two of them nothing is registered, so the
    # update gate is held for the whole sweep launch, not just for each child.
    with runner.starting_gate():
        _launch_sweep_locked(state, plan_id_value, materialize_companions, plan_id_factory)


def _launch_sweep_locked(
    state: SweepState,
    plan_id_value: str | None,
    materialize_companions: MaterializeCompanions,
    plan_id_factory: PlanIdFactory = plan_id,
) -> None:
    if len(state.cases) > MAX_SWEEP_CASES:
        raise OlgaInputError(
            f"Sweep registry exceeds the {MAX_SWEEP_CASES}-case execution limit."
        )
    with workspace.expected_context(state.context_generation):
        with state.lock:
            if state.started_monotonic is not None:
                raise OlgaInputError("Sweep has already been started.")
            try:
                current_plan_id = plan_id_factory(
                    state.base,
                    state.cases,
                    state.timeout_s,
                    state.detection,
                    state.strategy,
                    state.sweeps,
                )
            except OSError:
                current_plan_id = None
            if (
                not plan_id_value
                or plan_id_value != state.plan_id
                or current_plan_id != state.plan_id
            ):
                raise OlgaInputError(
                    "Sweep plan changed after preview; review and approve the current plan."
                )
            fresh_detection = runner.revalidate_pinned_detection(
                state.base, state.detection
            )
            invalid = [case for case in state.cases if not case.valid]
            if invalid:
                raise OlgaInputError(
                    "Sweep contains invalid generated case(s); fix the preview before execution."
                )

            selection_ids: list[str] = []
            for case in state.cases:
                if genkey_static.file_sha256(case.path) != case.source_sha256:
                    raise OlgaInputError(
                        "Sweep plan changed before child companions were staged; review a fresh preview."
                    )
                expected_source_hash = expected_staged_source_sha256(
                    case.path, case.companions, case.path.parent
                )
                case.pvt_files = materialize_companions(state.base, case.path)
                if genkey_static.file_sha256(
                    case.path
                ) != expected_source_hash or not staged_companions_match(
                    case.companions, case.path.parent
                ):
                    raise OlgaInputError(
                        "Sweep plan changed while child companions were staged; review a fresh preview."
                    )
                selection_ids.append(
                    runner.selection_id_for(case.path, fresh_detection, state.timeout_s)
                )

            state.started_monotonic = time.monotonic()
            for case, selection_id in zip(state.cases, selection_ids, strict=True):
                try:
                    started = runner.execute_run(
                        str(case.path),
                        approved=True,
                        timeout_s=state.timeout_s,
                        selection_id=selection_id,
                        pinned_detection=fresh_detection,
                    )
                except OlgaInputError as exc:
                    case.start_error = str(exc)
                    continue
                case.run_id = str(started["run_id"])


def materialize_pvt_companions(base: Path, case: Path) -> list[str]:
    approved = effective_companion_manifest(case, base)
    expected_source_hash = expected_staged_source_sha256(case, approved, case.parent)
    stage_companions(case, case, case.parent, fallback_source=base)
    if genkey_static.file_sha256(case) != expected_source_hash:
        raise OlgaInputError(
            "Sweep child source changed while companions were staged; review a fresh preview."
        )
    staged = companion_manifest(case)
    return [
        str(entry["resolved_path"])
        for entry in staged
        if entry["kind"] == "pvt"
        and entry["sha256"] is not None
        and entry["resolved_path"] is not None
    ]
