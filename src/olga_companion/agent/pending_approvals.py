"""Durable, exact-bound state machine for human-approved agent actions."""
from __future__ import annotations

import copy
import re
import secrets
import threading
import time
from dataclasses import asdict, dataclass, replace
from typing import Any

from . import approval_journal, history_policy, plan_model, plan_progress

TTL_SECONDS = 600
IN_FLIGHT_CAP = 256
TERMINAL_CAP = 256
_PENDING_ID = re.compile(r"[A-Za-z0-9_-]{32}")
_LOCK = threading.Lock()


class PendingApprovalError(ValueError):
    pass


class ApprovalUnavailableError(PendingApprovalError):
    """The approval is unknown, expired, or already used."""


class ApprovalExecutingError(PendingApprovalError):
    """The approval is already executing."""


class ApprovalClaimInactiveError(PendingApprovalError):
    """The in-flight claim is no longer active."""


@dataclass(frozen=True, slots=True)
class PendingApproval:
    action_kind: str
    args: dict[str, Any]
    call_id: str
    context_generation: int
    session_id: str


@dataclass(frozen=True, slots=True)
class CompletedApproval:
    approval: PendingApproval
    result: dict[str, Any]
    audit_state: str = "pending"
    resume_state: str = "pending"


@dataclass(frozen=True, slots=True)
class FailedApproval:
    approval: PendingApproval
    message: str


@dataclass(frozen=True, slots=True)
class RejectedApproval:
    approval: PendingApproval


@dataclass(frozen=True, slots=True)
class _ClaimedApproval:
    approval: PendingApproval
    pending_expires_at: float


ApprovalOutcome = CompletedApproval | FailedApproval | RejectedApproval
_PENDING: dict[str, tuple[float, PendingApproval]] = {}
_IN_FLIGHT: dict[str, _ClaimedApproval] = {}
_TERMINAL: dict[str, tuple[float, ApprovalOutcome]] = {}
_EXPIRES_EPOCH: dict[str, float] = {}


def _matches(record: PendingApproval, *, session_id: str, call_id: str, context_generation: int) -> bool:
    return record.session_id == session_id and record.call_id == call_id and record.context_generation == context_generation


def _approval(raw: dict[str, Any]) -> PendingApproval:
    return PendingApproval(str(raw["action_kind"]), dict(raw["args"]), str(raw["call_id"]), int(raw["context_generation"]), str(raw["session_id"]))


def _journal_record(status: str, approval: PendingApproval, **extra: Any) -> dict[str, Any]:
    return {"status": status, "approval": asdict(approval), **extra}


def _persist_terminal(pending_id: str, outcome: ApprovalOutcome) -> None:
    expires_epoch = time.time() + TTL_SECONDS
    if isinstance(outcome, CompletedApproval):
        raw = _journal_record(
            "completed", outcome.approval, result=outcome.result,
            audit_state=outcome.audit_state, resume_state=outcome.resume_state,
            expires_epoch=expires_epoch,
        )
    elif isinstance(outcome, FailedApproval):
        raw = _journal_record("uncertain", outcome.approval, message=outcome.message, expires_epoch=expires_epoch)
    else:
        raw = _journal_record("rejected", outcome.approval, expires_epoch=expires_epoch)
    approval_journal.commit(pending_id, raw)


def _purge_expired(now: float) -> None:
    for pending_id, (expires_at, _) in list(_PENDING.items()):
        if now > expires_at:
            del _PENDING[pending_id]
            _EXPIRES_EPOCH.pop(pending_id, None)
    for pending_id, (expires_at, outcome) in list(_TERMINAL.items()):
        if now > expires_at and not isinstance(outcome, FailedApproval):
            del _TERMINAL[pending_id]


def _evict_terminal() -> None:
    while len(_TERMINAL) > TERMINAL_CAP:
        del _TERMINAL[next(iter(_TERMINAL))]


def _restore() -> None:
    now_epoch, now = time.time(), time.monotonic()
    for pending_id, raw in approval_journal.load_all().items():
        try:
            approval = _approval(raw["approval"])
            remaining = float(raw.get("expires_epoch", now_epoch + TTL_SECONDS)) - now_epoch
            status = raw.get("status")
            if remaining < 0 and status not in {"uncertain", "in_flight"}:
                continue
            if status == "pending":
                _PENDING[pending_id] = (now + remaining, approval)
                epoch = raw.get("expires_epoch")
                if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
                    _EXPIRES_EPOCH[pending_id] = float(epoch)
            elif status == "completed":
                resume_state = str(raw.get("resume_state", "pending"))
                if resume_state == "in_progress":
                    resume_state = "pending"
                outcome: ApprovalOutcome = CompletedApproval(
                    approval, dict(raw.get("result") or {}),
                    str(raw.get("audit_state", "pending")), resume_state,
                )
                if raw.get("resume_state") == "in_progress":
                    _persist_terminal(pending_id, outcome)
                _TERMINAL[pending_id] = (now + remaining, outcome)
            elif status == "rejected":
                _TERMINAL[pending_id] = (now + remaining, RejectedApproval(approval))
            elif status in {"uncertain", "in_flight"}:
                outcome = FailedApproval(approval, str(raw.get("message") or "Dispatch outcome is uncertain."))
                _persist_terminal(pending_id, outcome)
                _TERMINAL[pending_id] = (now + TTL_SECONDS, outcome)
        except (KeyError, TypeError, ValueError, approval_journal.ApprovalJournalError):
            continue


def register(*, action_kind: str, args: dict[str, Any], call_id: str, context_generation: int, session_id: str) -> str:
    if not action_kind or not call_id or not session_id:
        raise PendingApprovalError("Pending approval identity is incomplete.")
    if "approval_token" in args:
        raise PendingApprovalError("Pending approval arguments must not contain a capability.")
    if not isinstance(context_generation, int) or isinstance(context_generation, bool) or context_generation < 0:
        raise PendingApprovalError("Pending approval context generation is invalid.")
    pending_id = secrets.token_urlsafe(24)
    record = PendingApproval(action_kind, copy.deepcopy(args), call_id, context_generation, session_id)
    is_plan = action_kind == plan_model.PLAN_KIND
    ttl = plan_model.PLAN_TTL_SECONDS if is_plan else TTL_SECONDS
    with _LOCK:
        now = time.monotonic()
        _purge_expired(now)
        expires_epoch = time.time() + ttl
        if is_plan:
            try:
                kinds = [step["kind"] for step in plan_model.canonical_steps(args.get("steps"))]
                digest = plan_model.digest(args, session_id, context_generation, call_id)
            except plan_model.PlanError as exc:
                raise PendingApprovalError(str(exc)) from exc
            plan_progress.create(pending_id, digest, kinds, expires_epoch)
        approval_journal.commit(
            pending_id,
            _journal_record("pending", record, expires_epoch=expires_epoch),
        )
        _PENDING[pending_id] = (now + ttl, record)
        _EXPIRES_EPOCH[pending_id] = expires_epoch
    return pending_id


def registered_expires_epoch(pending_id: str) -> float:
    """Wall-clock expiry recorded when this approval was issued. Checks are unchanged."""
    with _LOCK:
        return _EXPIRES_EPOCH[pending_id]


def claim(pending_id: str, *, session_id: str, call_id: str, context_generation: int) -> PendingApproval:
    if not _PENDING_ID.fullmatch(pending_id):
        raise ApprovalUnavailableError("Pending approval is unknown, expired, or already used.")
    with _LOCK:
        now = time.monotonic()
        _purge_expired(now)
        entry = _PENDING.get(pending_id)
        if entry is None:
            active = _IN_FLIGHT.get(pending_id)
            if active and _matches(active.approval, session_id=session_id, call_id=call_id, context_generation=context_generation):
                raise ApprovalExecutingError("Pending approval is already executing.")
            raise ApprovalUnavailableError("Pending approval is unknown, expired, or already used.")
        if not _matches(entry[1], session_id=session_id, call_id=call_id, context_generation=context_generation):
            raise PendingApprovalError("Pending approval does not match this session, call, or workspace context.")
        if len(_IN_FLIGHT) >= IN_FLIGHT_CAP:
            raise PendingApprovalError("Pending approval execution capacity is full; retry later.")
        approval_journal.commit(
            pending_id,
            _journal_record("in_flight", entry[1], message="Dispatch outcome is uncertain.", expires_epoch=time.time() + TTL_SECONDS),
        )
        del _PENDING[pending_id]
        _EXPIRES_EPOCH.pop(pending_id, None)
        _IN_FLIGHT[pending_id] = _ClaimedApproval(entry[1], entry[0])
        return copy.deepcopy(entry[1])


def release(pending_id: str, record: PendingApproval) -> None:
    with _LOCK:
        now = time.monotonic()
        entry = _IN_FLIGHT.get(pending_id)
        if entry is None or entry.approval != record:
            raise ApprovalClaimInactiveError("Pending approval claim is no longer active.")
        del _IN_FLIGHT[pending_id]
        if now <= entry.pending_expires_at:
            expires_epoch = time.time() + max(0, entry.pending_expires_at - now)
            approval_journal.commit(
                pending_id, _journal_record("pending", record, expires_epoch=expires_epoch),
            )
            _PENDING[pending_id] = (entry.pending_expires_at, record)
            _EXPIRES_EPOCH[pending_id] = expires_epoch


def complete(pending_id: str, record: PendingApproval, result: dict[str, Any]) -> CompletedApproval:
    with _LOCK:
        entry = _IN_FLIGHT.get(pending_id)
        if entry is None or entry.approval != record:
            raise ApprovalClaimInactiveError("Pending approval claim is no longer active.")
        outcome = CompletedApproval(copy.deepcopy(record), history_policy.sanitize_tool_result(result))
        _persist_terminal(pending_id, outcome)
        del _IN_FLIGHT[pending_id]
        _TERMINAL[pending_id] = (time.monotonic() + TTL_SECONDS, outcome)
        _evict_terminal()
        return copy.deepcopy(outcome)


def fail(pending_id: str, record: PendingApproval, message: str) -> FailedApproval:
    with _LOCK:
        entry = _IN_FLIGHT.get(pending_id)
        if entry is None or entry.approval != record:
            raise ApprovalClaimInactiveError("Pending approval claim is no longer active.")
        outcome = FailedApproval(copy.deepcopy(record), message)
        _persist_terminal(pending_id, outcome)
        del _IN_FLIGHT[pending_id]
        _TERMINAL[pending_id] = (time.monotonic() + TTL_SECONDS, outcome)
        _evict_terminal()
        return copy.deepcopy(outcome)


def recover(pending_id: str, *, session_id: str, call_id: str, context_generation: int) -> ApprovalOutcome | None:
    if not _PENDING_ID.fullmatch(pending_id):
        return None
    with _LOCK:
        _purge_expired(time.monotonic())
        entry = _TERMINAL.get(pending_id)
        if entry is None:
            return None
        if not _matches(entry[1].approval, session_id=session_id, call_id=call_id, context_generation=context_generation):
            raise PendingApprovalError("Pending approval does not match this session, call, or workspace context.")
        return copy.deepcopy(entry[1])


def mark_audit(pending_id: str, succeeded: bool) -> CompletedApproval:
    with _LOCK:
        entry = _TERMINAL.get(pending_id)
        if entry is None or not isinstance(entry[1], CompletedApproval):
            raise PendingApprovalError("Completed approval is unavailable.")
        outcome = replace(entry[1], audit_state="persisted" if succeeded else "missing")
        _persist_terminal(pending_id, outcome)
        _TERMINAL[pending_id] = (entry[0], outcome)
        return copy.deepcopy(outcome)


def begin_resume(pending_id: str, **identity: Any) -> tuple[CompletedApproval, bool]:
    with _LOCK:
        entry = _TERMINAL.get(pending_id)
        if entry is None or not isinstance(entry[1], CompletedApproval):
            raise PendingApprovalError("Completed approval is unavailable for continuation.")
        outcome = entry[1]
        if not _matches(outcome.approval, **identity):
            raise PendingApprovalError("Pending approval does not match this session, call, or workspace context.")
        if outcome.resume_state != "pending":
            return copy.deepcopy(outcome), False
        outcome = replace(outcome, resume_state="in_progress")
        _persist_terminal(pending_id, outcome)
        _TERMINAL[pending_id] = (entry[0], outcome)
        return copy.deepcopy(outcome), True


def finish_resume(pending_id: str, succeeded: bool | None) -> CompletedApproval:
    with _LOCK:
        entry = _TERMINAL.get(pending_id)
        if entry is None or not isinstance(entry[1], CompletedApproval):
            raise PendingApprovalError("Completed approval is unavailable for continuation.")
        outcome = replace(entry[1], resume_state="uncertain" if succeeded is None else ("resumed" if succeeded else "pending"))
        _persist_terminal(pending_id, outcome)
        _TERMINAL[pending_id] = (entry[0], outcome)
        return copy.deepcopy(outcome)


def reject(pending_id: str, *, session_id: str, call_id: str, context_generation: int) -> RejectedApproval:
    record = claim(pending_id, session_id=session_id, call_id=call_id, context_generation=context_generation)
    with _LOCK:
        entry = _IN_FLIGHT.get(pending_id)
        if entry is None or entry.approval != record:
            raise ApprovalClaimInactiveError("Pending approval claim is no longer active.")
        outcome = RejectedApproval(record)
        _persist_terminal(pending_id, outcome)
        del _IN_FLIGHT[pending_id]
        _TERMINAL[pending_id] = (time.monotonic() + TTL_SECONDS, outcome)
        _evict_terminal()
        return copy.deepcopy(outcome)


def session_has_pending(
    session_id: str, *, action_kinds: frozenset[str] | None = None
) -> bool:
    """True when this session still has an approval waiting or already executing.

    action_kinds limits the check to those actions. A pending run stays invisible
    to a save-announcement notice.
    """
    def wanted(record: PendingApproval) -> bool:
        return record.session_id == session_id and (
            action_kinds is None or record.action_kind in action_kinds
        )

    with _LOCK:
        _purge_expired(time.monotonic())
        waiting = any(wanted(record) for _expires, record in _PENDING.values())
        executing = any(wanted(item.approval) for item in _IN_FLIGHT.values())
        return waiting or executing


def is_actionable(
    pending_id: str,
    *,
    session_id: str,
    call_id: str,
    context_generation: int,
    current_generation: int | None = None,
) -> bool:
    """True while a click can still dispatch; a moved workspace generation is dead."""
    if not _PENDING_ID.fullmatch(pending_id):
        return False
    if current_generation is not None and current_generation != context_generation:
        return False
    with _LOCK:
        _purge_expired(time.monotonic())
        entry = _PENDING.get(pending_id)
        return bool(entry and _matches(entry[1], session_id=session_id, call_id=call_id, context_generation=context_generation))


def revoke_all() -> int:
    with _LOCK:
        count = len(_PENDING) + len(_IN_FLIGHT)
        _PENDING.clear()
        _IN_FLIGHT.clear()
        _TERMINAL.clear()
        _EXPIRES_EPOCH.clear()
        approval_journal.clear()
        return count


_restore()
