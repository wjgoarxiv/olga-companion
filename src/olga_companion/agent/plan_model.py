"""Pure rules for a bounded approval plan: step shape, allowed kinds, digest."""
from __future__ import annotations

import hashlib
import json
from typing import Any

PLAN_KIND = "action_plan"
# The plan card stays approvable far longer than one 600 s step token; each step
# mints its own token at its own turn.
PLAN_TTL_SECONDS = 1800
MAX_STEPS = 6
MAX_RUN_STEPS = 1
STEP_KINDS = ("fluids_draft_mfl", "fluids_generate_tab", "case_publish", "run_execute")
# fluids_generate_tab is the in-app table generator: a step only in local PVT builds that
# set OLGA_COMPANION_NATIVE_TAB=1. Everywhere else it is accepted by shape and refused.
UNAVAILABLE_KINDS = frozenset({"fluids_generate_tab"})
OFFERED_KINDS = tuple(kind for kind in STEP_KINDS if kind not in UNAVAILABLE_KINDS)
NEVER_IN_PLAN = ("run_cancel", "sweep_cancel", "sweep_execute", "genkey_save", "multiflash_open", "fluids_starter_tab")
CAPABILITY_KEYS = frozenset({"approval_token", "idempotency_key"})
_STEP_KEYS = frozenset({"kind", "args", "source_from_step"})


class PlanError(ValueError):
    """The submitted plan is malformed or breaks a plan rule."""


def _native_tab(native_tab: bool | None) -> bool:
    from .. import config

    return config.native_tab_enabled() if native_tab is None else native_tab


def unavailable_kinds(native_tab: bool | None = None) -> frozenset[str]:
    """Step kinds this build refuses; the table generator is available only with the flag."""
    return frozenset() if _native_tab(native_tab) else UNAVAILABLE_KINDS


def offered_kinds(native_tab: bool | None = None) -> tuple[str, ...]:
    """Step kinds the model may name in this build."""
    gone = unavailable_kinds(native_tab)
    return tuple(kind for kind in STEP_KINDS if kind not in gone)


def _normalize(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise PlanError("A plan needs at least one step.")
    steps: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            raise PlanError("Each plan step needs a kind.")
        args = item.get("args", {})
        if not isinstance(args, dict):
            raise PlanError("A plan step's args must be an object.")
        step: dict[str, Any] = {"kind": item["kind"], "args": json.loads(json.dumps(args))}
        if "source_from_step" in item:
            step["source_from_step"] = item["source_from_step"]
        steps.append(step)
    return steps


def canonical_steps(raw: Any) -> list[dict[str, Any]]:
    """Return the ordered steps after every plan rule; raises PlanError."""
    steps = _normalize(raw)
    if len(steps) > MAX_STEPS:
        raise PlanError(f"A plan holds at most {MAX_STEPS} steps.")
    for number, (item, step) in enumerate(zip(raw, steps), start=1):
        extra = set(item) - _STEP_KEYS
        if extra:
            raise PlanError(f"Step {number} has an unknown field: {sorted(extra)[0]}.")
        kind = step["kind"]
        if kind in NEVER_IN_PLAN:
            raise PlanError(f"{kind} never joins a plan; it needs its own approval card.")
        if kind not in STEP_KINDS:
            raise PlanError(f"{kind} cannot be a plan step.")
        if CAPABILITY_KEYS & set(step["args"]):
            raise PlanError("A plan step must not carry an approval capability.")
        if "source_from_step" in step:
            _check_binding(number, step, steps)
        elif kind == "run_execute" and not step["args"].get("source"):
            raise PlanError(
                f"Step {number}: a run_execute step without source_from_step must name its source."
            )
    if sum(step["kind"] == "run_execute" for step in steps) > MAX_RUN_STEPS:
        raise PlanError("A plan holds at most one run_execute step.")
    return steps


def _check_binding(number: int, step: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    if step["kind"] != "run_execute":
        raise PlanError(f"Step {number}: only run_execute can be bound to an earlier step.")
    source = step["source_from_step"]
    if isinstance(source, bool) or not isinstance(source, int) or not 1 <= source < number:
        raise PlanError(f"Step {number} must be bound to an earlier step.")
    if steps[source - 1]["kind"] != "case_publish":
        raise PlanError(f"Step {number} can only run a case that step {source} publishes.")
    if {"source", "selection_id"} & set(step["args"]):
        raise PlanError(
            f"Step {number} takes its case from step {source}; give neither source nor selection_id."
        )


def digest(args: dict[str, Any], session_id: str, context_generation: int, call_id: str) -> str:
    """Bind the ordered list, the session, the workspace generation and the plan call."""
    body = json.dumps(
        {
            "steps": _normalize(args.get("steps")),
            "session": session_id,
            "generation": context_generation,
            "call": call_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
