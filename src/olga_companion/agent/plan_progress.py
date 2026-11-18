"""Journaled per-step progress of one approved plan, so a restart can say what ran."""
from __future__ import annotations

from typing import Any

from . import approval_journal

WAITING = "waiting"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
UNCERTAIN = "uncertain"
NOT_RUN = "not_run"


def _commit(pending_id: str, record: dict[str, Any]) -> None:
    approval_journal.commit(pending_id, record, approval_journal.PLAN_SUBDIR)


def create(pending_id: str, digest: str, kinds: list[str], expires_epoch: float) -> None:
    _commit(
        pending_id,
        {
            "digest": digest,
            "expires_epoch": expires_epoch,
            "steps": [
                {"index": number, "kind": kind, "state": WAITING}
                for number, kind in enumerate(kinds, start=1)
            ],
        },
    )


def load(pending_id: str) -> dict[str, Any] | None:
    return approval_journal.load_one(pending_id, approval_journal.PLAN_SUBDIR)


def mark(
    pending_id: str,
    index: int,
    state: str,
    error: str = "",
    *,
    code: str = "",
    result: dict[str, Any] | None = None,
) -> None:
    """Record a step's state; a finished step keeps its result for a later report."""
    record = load(pending_id)
    if record is None:
        return
    for step in record["steps"]:
        if step["index"] == index:
            step["state"] = state
            if error:
                step["error"] = error
            if code:
                step["code"] = code
            if result:
                step["result"] = result
    _commit(pending_id, record)


def settle(pending_id: str) -> None:
    """Close the plan: whatever never started is not run."""
    record = load(pending_id)
    if record is None:
        return
    for step in record["steps"]:
        if step["state"] == WAITING:
            step["state"] = NOT_RUN
    _commit(pending_id, record)


def report(pending_id: str) -> list[dict[str, Any]]:
    """Step states as a restart must show them: a step caught mid-run is uncertain."""
    record = load(pending_id)
    if record is None:
        return []
    shown = {RUNNING: UNCERTAIN, WAITING: NOT_RUN}
    return [
        {**step, "state": shown.get(step["state"], step["state"])}
        for step in record["steps"]
    ]
