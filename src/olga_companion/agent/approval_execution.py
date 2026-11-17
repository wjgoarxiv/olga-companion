"""One-shot approval execution with exact-context result recovery."""
from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, assert_never

from .. import genkey_static, workspace
from ..runtime_logging import LOGGER_NAME
from . import (
    approval_continuation,
    approvals,
    history,
    pending_approvals,
    plan_execution,
    plan_model,
    plan_progress,
    tools,
)
from .chat_singleflight import session_single_flight_sync

ApprovalResumeError = approval_continuation.ApprovalResumeError

_LOG = logging.getLogger(__name__)
_UNCERTAIN_MESSAGE = (
    "The approved action outcome could not be confirmed. Inspect run history before retrying."
)
_PUBLISH_RECOVERY = {
    "unsafe_destination": (
        "저장 위치는 워크스페이스 루트 안의 기존 폴더여야 합니다. "
        "현재 케이스 옆에 저장하려면 그 케이스의 워크스페이스 상대 폴더를 유지한 채 새 파일 이름을 붙이세요."
    ),
    "destination_collision": "그 이름의 파일이 이미 있습니다. 다른 파일 이름을 적으세요.",
    "pvt_companion": "저장할 폴더에 이 케이스가 쓰는 유체 표가 없습니다. 표를 그 폴더에 둔 뒤 다시 요청하세요.",
    "stale_source": "원본 케이스가 검토 뒤에 바뀌었습니다. 계획을 다시 만든 뒤 저장하세요.",
    "stale_context": "작업 폴더가 바뀌었습니다. 현재 폴더에서 다시 요청하세요.",
    "invalid_compile": "검토한 컴파일이 저장할 수 있는 상태가 아닙니다. 검증을 다시 하세요.",
    "legacy_compile": "이 컴파일은 저장할 수 없습니다. 케이스를 다시 검증하세요.",
    "transaction_mismatch": "검토한 거래와 저장 요청이 다릅니다. 계획을 다시 만든 뒤 저장하세요.",
    "source_mismatch": "검토한 원본과 저장 요청이 다릅니다. 계획을 다시 만든 뒤 저장하세요.",
    "compile_mismatch": "검토한 컴파일과 저장 요청이 다릅니다. 계획을 다시 만든 뒤 저장하세요.",
    "missing_backup": "검토 백업이 없습니다. 계획을 다시 만든 뒤 저장하세요.",
    "invalid_backup": "검토 백업이 원본과 다릅니다. 계획을 다시 만든 뒤 저장하세요.",
    "receipt_mismatch": "저장된 결과와 목적지가 다릅니다. 계획을 다시 만든 뒤 저장하세요.",
}
_PUBLISH_RECOVERY_EN = {
    "unsafe_destination": (
        "The destination must be an existing folder inside the workspace root. "
        "To save beside the current case, keep that case's workspace-relative folder "
        "and append a new file name."
    ),
    "destination_collision": "A file with that name already exists. Choose a different file name.",
    "pvt_companion": (
        "The destination folder is missing the fluid table this case uses. "
        "Put the table in that folder and request again."
    ),
    "stale_source": "The source case changed after review. Re-plan and save again.",
    "stale_context": "The workspace folder changed. Request again from the current folder.",
    "invalid_compile": "The reviewed compile is not in a savable state. Validate again.",
    "legacy_compile": "This compile cannot be saved. Validate the case again.",
    "transaction_mismatch": "The reviewed transaction and the save request differ. Re-plan and save again.",
    "source_mismatch": "The reviewed source and the save request differ. Re-plan and save again.",
    "compile_mismatch": "The reviewed compile and the save request differ. Re-plan and save again.",
    "missing_backup": "There is no review backup. Re-plan and save again.",
    "invalid_backup": "The review backup differs from the source. Re-plan and save again.",
    "receipt_mismatch": "The saved result and the destination differ. Re-plan and save again.",
}
USED_SENTENCE = "승인 시간이 지났습니다. 다시 요청하세요."
EXECUTING_SENTENCE = "이 승인은 이미 처리 중입니다."
INACTIVE_SENTENCE = "이 승인 요청은 끝났습니다. 다시 요청하세요."
# The model reads the tool_result in the session's language, like the heal does.
_UNACTIONABLE_EN = {
    USED_SENTENCE: "The approval expired. Request it again.",
    EXECUTING_SENTENCE: "This approval is already being processed.",
    INACTIVE_SENTENCE: "This approval request has ended. Request it again.",
}
_APPROVAL_ENVELOPE_KEYS = (
    "turn_id",
    "request_id",
    "workspace_root",
    "provider",
    "model",
    "locale",
)


def _diagnose(
    event: str,
    action_kind: str,
    stage: str,
    *,
    exc: BaseException | None = None,
    message: str | None = None,
) -> None:
    """One sidecar.log line naming the action and cause of a failed or uncertain click.

    The diagnostics bundle only carries this logger, so without it a 409 report
    shows that an approval failed but never which action or why.
    """
    from .runtime import _sanitize_failure_text

    location = "-"
    tb = exc.__traceback__ if exc is not None else None
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    if tb is not None:
        location = f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}"
    detail = _sanitize_failure_text(message if message is not None else str(exc or ""), 300)
    logging.getLogger(LOGGER_NAME).warning(
        "%s action=%s stage=%s kind=%s at=%s detail=%s",
        event,
        action_kind,
        stage,
        type(exc).__name__ if exc is not None else "-",
        location,
        detail,
    )


def _refusal_locale(envelope: dict[str, Any]) -> str:
    """Turn locale for save-error text; old envelopes without one stay Korean."""
    locale = envelope.get("locale")
    return "en" if locale == "en" else "ko"


class ApprovalDispatchUncertainError(RuntimeError):
    """A dispatch raised after entry, so replay must not launch it again."""

    def __init__(self, message: str, steps: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.steps = steps

    def response(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "state": "uncertain",
            "resume_allowed": False,
            "message": str(self),
        }
        if self.steps:
            body["steps"] = self.steps
        return body


def _plan_steps(action_kind: str, pending_id: str) -> list[dict[str, Any]] | None:
    """Per-step done / uncertain / not-run states of a plan; None for any other action."""
    if action_kind != plan_model.PLAN_KIND:
        return None
    return plan_progress.report(pending_id) or None


def _plan_result_extra(action_kind: str, pending_id: str) -> dict[str, Any]:
    steps = _plan_steps(action_kind, pending_id)
    return {"steps": steps} if steps else {}


class ApprovalRejectedError(RuntimeError):
    """A human rejection is terminal and can never dispatch."""

    def response(self) -> dict[str, Any]:
        return {
            "state": "rejected",
            "resume_allowed": False,
            "message": "This approval was rejected by the user.",
        }


def _lost_claim_is_uncertain(exc: BaseException) -> None:
    """complete()/fail() after dispatch must not look like a click that never ran."""
    if (
        isinstance(exc, pending_approvals.PendingApprovalError)
        and str(exc) == "Pending approval claim is no longer active."
    ):
        raise ApprovalDispatchUncertainError(_UNCERTAIN_MESSAGE) from exc


def _seal_publish_refusal(
    pending_id: str,
    pending: pending_approvals.PendingApproval,
    message: str,
    locale: str = "ko",
) -> dict[str, Any] | None:
    refused = _publish_refusal(message, locale=locale)
    if refused is None:
        return None
    pending_approvals.fail(pending_id, pending, message)
    return {**refused, "name": pending.action_kind, "call_id": pending.call_id}


def _publish_refusal(message: str, locale: str = "ko") -> dict[str, Any] | None:
    code, separator, _detail = message.partition(": ")
    table = _PUBLISH_RECOVERY_EN if locale == "en" else _PUBLISH_RECOVERY
    sentence = table.get(code) if separator else None
    if sentence is None:
        return None
    visible = f"{code}: {sentence}"
    return {
        "state": "failed",
        "resume_allowed": False,
        "result": {"ok": False, "code": code, "error": visible},
    }


def _fail_closed(
    pending_id: str,
    pending: pending_approvals.PendingApproval,
    message: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    """Close a click whose outcome is known to be a failure: the reason is shown and the card is final."""
    pending_approvals.fail(pending_id, pending, message)
    _answer_failed_call(
        session_id=pending.session_id,
        pending_id=pending_id,
        call_id=pending.call_id,
        action_kind=pending.action_kind,
        message=message,
        extra=envelope,
    )
    try:
        history.append(
            pending.session_id,
            {
                "record": "approval",
                **envelope,
                "pending_id": pending_id,
                "name": pending.action_kind,
                "call_id": pending.call_id,
                "args": pending.args,
                "result": tools._cap({"error": message}),
                "state": "failed",
                "lifecycle": "failed",
                "reason": message,
                "resume_allowed": False,
                "workspace_generation": pending.context_generation,
            },
        )
    except (OSError, ValueError):
        _LOG.warning("Approval failure was sealed but its audit record failed.")
    return {
        "name": pending.action_kind,
        "call_id": pending.call_id,
        "state": "failed",
        "resume_allowed": False,
        "result": tools._cap({"error": message}),
    }


def _answer_failed_call(
    *,
    session_id: str,
    pending_id: str,
    call_id: str,
    action_kind: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist a `tool_result` error so replay never orphans the answered call.

    Best-effort and idempotent: a missing history or an already-answered call
    is left alone, and a journal failure never breaks the click response. The
    row carries a per-call `record_id`, so a repeat is skipped atomically.
    """
    try:
        records = history.read(session_id)
    except (OSError, ValueError):
        return
    for record in records:
        if (
            record.get("record") == "event"
            and record.get("type") == "tool_result"
            and record.get("call_id") == call_id
        ):
            return
    envelope: dict[str, Any] = dict(extra or {})
    for record in reversed(records):
        if record.get("record") != "approval" or record.get("call_id") != call_id:
            continue
        for key in _APPROVAL_ENVELOPE_KEYS:
            if key in record and key not in envelope:
                envelope[key] = record[key]
        if record.get("pending_id") == pending_id:
            break
    try:
        history.append(
            session_id,
            {
                "record": "event",
                "type": "tool_result",
                "record_id": history.tool_result_record_id(call_id),
                "name": action_kind,
                "call_id": call_id,
                "result": tools._cap(
                    {"error": message, **_plan_result_extra(action_kind, pending_id)}
                ),
                **envelope,
            },
        )
    except (OSError, ValueError):
        _LOG.warning("Approval failure answer could not be journaled.")


def answer_unactionable_call(
    *,
    session_id: str,
    pending_id: str,
    call_id: str,
    message: str,
) -> None:
    """Answer a call whose approval is already expired, used or rejected.

    Only a history approval with this `pending_id` and `call_id` that is no longer
    actionable is answered, under the session lock; anything else is ignored. The
    pending record is gone, so the action name comes from that history record.
    """
    with session_single_flight_sync(session_id):
        try:
            records = history.read(session_id)
        except (OSError, ValueError):
            return
        approval = next(
            (
                record
                for record in reversed(records)
                if record.get("record") == "approval"
                and record.get("pending_id") == pending_id
                and record.get("call_id") == call_id
            ),
            None,
        )
        if approval is None:
            return
        if pending_approvals.is_actionable(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=approval.get("workspace_generation"),
        ):
            return
        if _refusal_locale(approval) == "en":
            message = _UNACTIONABLE_EN.get(message, message)
        _answer_failed_call(
            session_id=session_id,
            pending_id=pending_id,
            call_id=call_id,
            action_kind=str(approval.get("name") or ""),
            message=message,
        )


def _response(outcome: pending_approvals.CompletedApproval) -> dict[str, Any]:
    if outcome.resume_state == "uncertain":
        return {
            "name": outcome.approval.action_kind,
            "call_id": outcome.approval.call_id,
            "result": outcome.result,
            "state": "uncertain",
            "resume_allowed": False,
        }
    awaiting_resume = outcome.resume_state != "resumed"
    return {
        "name": outcome.approval.action_kind,
        "call_id": outcome.approval.call_id,
        "result": outcome.result,
        "state": "resume_pending" if awaiting_resume else "resumed",
        "resume_allowed": awaiting_resume,
    }


def _pending_approval_envelope(
    session_id: str, pending_id: str
) -> dict[str, Any]:
    """Recover only canonical identity from the matching pending audit record."""
    try:
        records = history.read(session_id)
    except (OSError, ValueError):
        return {}
    for record in reversed(records):
        if (
            record.get("record") == "approval"
            and record.get("state") == "pending"
            and record.get("pending_id") == pending_id
        ):
            return {
                key: record[key]
                for key in _APPROVAL_ENVELOPE_KEYS
                if key in record
            }
    return {}


def execute(
    *,
    pending_id: str,
    session_id: str,
    call_id: str,
    context_generation: int,
) -> dict[str, Any]:
    """Dispatch once, replay a terminal result, and never reopen uncertainty."""
    with session_single_flight_sync(session_id):
        return _execute_locked(
            pending_id=pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=context_generation,
        )


def _execute_locked(
    *,
    pending_id: str,
    session_id: str,
    call_id: str,
    context_generation: int,
) -> dict[str, Any]:
    with workspace.expected_context(context_generation):
        recovered = pending_approvals.recover(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=context_generation,
        )
        match recovered:
            case pending_approvals.CompletedApproval():
                return _response(recovered)
            case pending_approvals.FailedApproval(approval=approval, message=message):
                envelope = _pending_approval_envelope(session_id, pending_id)
                refused = _publish_refusal(message, locale=_refusal_locale(envelope))
                if refused is not None:
                    _answer_failed_call(
                        session_id=session_id,
                        pending_id=pending_id,
                        call_id=approval.call_id,
                        action_kind=approval.action_kind,
                        message=message,
                        extra=envelope,
                    )
                    return {**refused, "name": approval.action_kind, "call_id": approval.call_id}
                _answer_failed_call(
                    session_id=session_id,
                    pending_id=pending_id,
                    call_id=approval.call_id,
                    action_kind=approval.action_kind,
                    message=message,
                    extra=envelope,
                )
                _diagnose("approval_uncertain", approval.action_kind, "replay", message=message)
                raise ApprovalDispatchUncertainError(
                    message, _plan_steps(approval.action_kind, pending_id)
                )
            case pending_approvals.RejectedApproval():
                raise ApprovalRejectedError("This approval was rejected.")
            case None:
                pass
            case unreachable:
                assert_never(unreachable)

        pending = pending_approvals.claim(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=context_generation,
        )
        try:
            payload = tools.approval_payload(pending.action_kind, pending.args)
            # A plan mints a fresh single-use token per step, at that step's turn.
            capability = (
                ""
                if pending.action_kind == plan_model.PLAN_KIND
                else approvals.mint(
                    pending.action_kind,
                    payload,
                    context_generation=context_generation,
                )["token"]
            )
        except (
            tools.ToolError,
            workspace.WorkspaceError,
            genkey_static.OlgaInputError,
        ) as exc:
            envelope = _pending_approval_envelope(pending.session_id, pending_id)
            refused = _seal_publish_refusal(
                pending_id, pending, str(exc), locale=_refusal_locale(envelope)
            )
            if refused is not None:
                _answer_failed_call(
                    session_id=pending.session_id,
                    pending_id=pending_id,
                    call_id=pending.call_id,
                    action_kind=pending.action_kind,
                    message=str(exc),
                    extra=envelope,
                )
                return refused
            _diagnose("approval_failed", pending.action_kind, "payload", exc=exc)
            return _fail_closed(pending_id, pending, str(exc), envelope)
        except approvals.ApprovalError:
            pending_approvals.release(pending_id, pending)
            raise

        try:
            if pending.action_kind == plan_model.PLAN_KIND:
                locale = _refusal_locale(_pending_approval_envelope(pending.session_id, pending_id))
                result = plan_execution.run(
                    pending_id,
                    pending,
                    refusal=lambda text: _publish_refusal(text, locale=locale),
                )
                if result["state"] == "uncertain":
                    raise plan_execution.PlanUncertainError(result["steps"])
            else:
                result = tools.dispatch(
                    pending.action_kind,
                    {
                        **pending.args,
                        "approval_token": capability,
                        "idempotency_key": pending_id,
                    },
                )
        except tools.ToolPreDispatchError:
            pending_approvals.release(pending_id, pending)
            raise
        except tools.ToolFailedError as exc:
            # A refusal (nothing started) or a kept-file failure: the outcome is known, so it reads as failed.
            _diagnose("approval_failed", pending.action_kind, "dispatch", exc=exc)
            try:
                return _fail_closed(
                    pending_id, pending, str(exc), _pending_approval_envelope(pending.session_id, pending_id)
                )
            except pending_approvals.PendingApprovalError as lost:
                _lost_claim_is_uncertain(lost)
                raise
        except tools.ToolError as exc:
            try:
                envelope = _pending_approval_envelope(pending.session_id, pending_id)
                refused = _seal_publish_refusal(
                    pending_id, pending, str(exc), locale=_refusal_locale(envelope)
                )
            except pending_approvals.PendingApprovalError as lost:
                _lost_claim_is_uncertain(lost)
                raise
            if refused is not None:
                _answer_failed_call(
                    session_id=pending.session_id,
                    pending_id=pending_id,
                    call_id=pending.call_id,
                    action_kind=pending.action_kind,
                    message=str(exc),
                    extra=envelope,
                )
                return refused
            _diagnose("approval_uncertain", pending.action_kind, "dispatch", exc=exc)
            try:
                pending_approvals.fail(pending_id, pending, _UNCERTAIN_MESSAGE)
            except pending_approvals.PendingApprovalError as lost:
                _lost_claim_is_uncertain(lost)
                raise
            _answer_failed_call(
                session_id=pending.session_id,
                pending_id=pending_id,
                call_id=pending.call_id,
                action_kind=pending.action_kind,
                message=_UNCERTAIN_MESSAGE,
                extra=envelope,
            )
            raise ApprovalDispatchUncertainError(_UNCERTAIN_MESSAGE) from exc
        except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - seals uncertainty
            _diagnose("approval_uncertain", pending.action_kind, "dispatch", exc=exc)
            try:
                pending_approvals.fail(pending_id, pending, _UNCERTAIN_MESSAGE)
            except pending_approvals.PendingApprovalError as lost:
                _lost_claim_is_uncertain(lost)
                raise
            envelope = _pending_approval_envelope(pending.session_id, pending_id)
            _answer_failed_call(
                session_id=pending.session_id,
                pending_id=pending_id,
                call_id=pending.call_id,
                action_kind=pending.action_kind,
                message=_UNCERTAIN_MESSAGE,
                extra=envelope,
            )
            raise ApprovalDispatchUncertainError(
                _UNCERTAIN_MESSAGE, _plan_steps(pending.action_kind, pending_id)
            ) from None

        try:
            completed = pending_approvals.complete(pending_id, pending, result)
        except pending_approvals.PendingApprovalError as lost:
            _lost_claim_is_uncertain(lost)
            raise
        audit_succeeded = False
        try:
            envelope = _pending_approval_envelope(pending.session_id, pending_id)
            history.append(
                pending.session_id,
                {
                    "record": "approval",
                    **envelope,
                    "pending_id": pending_id,
                    "name": pending.action_kind,
                    "call_id": pending.call_id,
                    "args": pending.args,
                    "result": completed.result,
                    "state": "resume_pending",
                    "lifecycle": "finalizing",
                    "resume_allowed": True,
                    "workspace_generation": pending.context_generation,
                },
            )
            audit_succeeded = True
        except (OSError, ValueError):
            _LOG.warning(
                "Approval dispatch succeeded but its chat audit record could not be persisted."
            )
        completed = pending_approvals.mark_audit(pending_id, audit_succeeded)
        return _response(completed)


async def resume(
    *,
    pending_id: str,
    session_id: str,
    call_id: str,
    context_generation: int,
    event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    # The generation check is synchronous. Holding the workspace lock across the
    # continuation would make /api/workspace/* wait for the whole model turn.
    with workspace.expected_context(context_generation):
        pass
    return await approval_continuation.resume(
        pending_id=pending_id,
        session_id=session_id,
        call_id=call_id,
        context_generation=context_generation,
        event_sink=event_sink,
    )


def validate_resume(
    *, pending_id: str, session_id: str, call_id: str, context_generation: int
) -> None:
    with workspace.expected_context(context_generation):
        outcome = pending_approvals.recover(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=context_generation,
        )
    if not isinstance(outcome, pending_approvals.CompletedApproval):
        raise pending_approvals.PendingApprovalError(
            "Completed approval is unavailable for continuation."
        )


def reject(
    *, pending_id: str, session_id: str, call_id: str, context_generation: int
) -> dict[str, Any]:
    with session_single_flight_sync(session_id), workspace.expected_context(context_generation):
        recovered = pending_approvals.recover(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=context_generation,
        )
        if isinstance(recovered, pending_approvals.RejectedApproval):
            return {"state": "rejected", "resume_allowed": False}
        if recovered is not None:
            raise pending_approvals.PendingApprovalError(
                "A terminal approval cannot be rejected."
            )
        rejected = pending_approvals.reject(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=context_generation,
        )
        try:
            envelope = _pending_approval_envelope(session_id, pending_id)
            history.append(
                session_id,
                {
                    "record": "approval",
                    **envelope,
                    "pending_id": pending_id,
                    "name": rejected.approval.action_kind,
                    "call_id": call_id,
                    "state": "rejected",
                    "lifecycle": "rejected",
                    "reason": "Rejected by the user.",
                    "workspace_generation": context_generation,
                },
            )
        except (OSError, ValueError):
            _LOG.warning("Approval rejection was journaled but its chat audit record failed.")
        _answer_failed_call(
            session_id=session_id,
            pending_id=pending_id,
            call_id=call_id,
            action_kind=rejected.approval.action_kind,
            message="Rejected by the user.",
            extra=_pending_approval_envelope(session_id, pending_id),
        )
        return {"state": "rejected", "resume_allowed": False}
