from __future__ import annotations

from typing import Any

from . import genkey_static, runner, workspace  # noqa: F401  # compatibility surface
from .genkey_static import OlgaInputError
from . import sweep_launch as _launch
from . import sweep_monitor as _monitor
from . import sweep_selection as _selection
from . import sweep_status as _status

MAX_SWEEP_CASES = _selection.MAX_SWEEP_CASES
MAX_SWEEP_SPECS = _selection.MAX_SWEEP_SPECS
MAX_SWEEP_VALUES_PER_SPEC = _selection.MAX_SWEEP_VALUES_PER_SPEC
MAX_SWEEP_SPEC_CHARS = _selection.MAX_SWEEP_SPEC_CHARS
UnknownSweepError = _selection.UnknownSweepError
SweepCaseState = _selection.SweepCaseState
SweepState = _selection.SweepState

# Preserve the existing module-level compatibility seams while ownership moves
# to cohesive implementation modules.
_SWEEPS = _selection.SWEEPS
_REGISTRY_LOCK = _selection.REGISTRY_LOCK
_plan_id = _selection.plan_id
_case_from_entry = _selection.case_from_entry
_materialize_pvt_companions = _launch.materialize_pvt_companions
_case_status = _monitor.case_status
_aggregate_state = _monitor.aggregate_state


def approval_payload(sweep_id: str, plan_id: str) -> dict[str, str]:
    return _selection.approval_payload(sweep_id, plan_id)


def _get_state(sweep_id: str) -> SweepState:
    return _selection.get_state(sweep_id, _SWEEPS, _REGISTRY_LOCK)


def _status_for_state(state: SweepState) -> dict[str, Any]:
    return _status.status_for_state(
        state,
        _case_status,
        _aggregate_state,
        approval_payload,
    )


def preview_sweep(
    base_path: str,
    sweeps: list[str],
    strategy: str = "oat",
    max_cases: int = 20,
    timeout_s: int = 3600,
) -> dict[str, Any]:
    state = _selection.create_sweep(
        base_path,
        sweeps,
        strategy,
        max_cases,
        timeout_s,
        _case_from_entry,
        _plan_id,
        _SWEEPS,
        _REGISTRY_LOCK,
    )
    return _status_for_state(state)


def execute_sweep(
    sweep_id: str, approved: bool = False, plan_id: str | None = None
) -> dict[str, Any]:
    if not approved:
        raise OlgaInputError(
            "Sweep execution requires explicit approval after reviewing the generated case matrix."
        )
    state = _get_state(sweep_id)
    _launch.launch_sweep(state, plan_id, _materialize_pvt_companions, _plan_id)
    return _status_for_state(state)


def sweep_status(sweep_id: str) -> dict[str, Any]:
    return _status_for_state(_get_state(sweep_id))


def cancel_sweep(sweep_id: str) -> dict[str, Any]:
    state = _get_state(sweep_id)
    _monitor.cancel_state(state)
    return _status_for_state(state)
