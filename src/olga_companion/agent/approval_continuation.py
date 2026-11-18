"""Provider continuation after an authoritative approval receipt exists."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from ..llm import catalog as llm_catalog
from . import approval_event_persistence, chat, chat_replay, history, pending_approvals
from .chat_singleflight import session_single_flight


class ApprovalResumeError(RuntimeError):
    pass


class ApprovalResumeIdentityError(ApprovalResumeError):
    """The original provider/model is unrecorded or invalid; retrying cannot help."""


EventSink = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(sink: EventSink | None, event: dict[str, Any]) -> None:
    if sink is not None:
        await sink(event)


def _pending_record(records: list[dict[str, Any]], pending_id: str) -> dict[str, Any]:
    for record in reversed(records):
        if record.get("record") == "approval" and record.get("pending_id") == pending_id:
            return record
    return {}


def original_identity(record: dict[str, Any]) -> tuple[str, str]:
    """Return the provider/model that created the approval, or fail closed.

    Conversation history is never replayed to a provider the approval did not
    originate from, so a missing or malformed identity ends the continuation.
    """
    provider = record.get("provider")
    model = record.get("model")
    if not isinstance(provider, str) or not llm_catalog.is_known_provider(provider):
        raise ApprovalResumeIdentityError(
            "The approval does not record a supported AI provider. The approved action "
            "already ran; ask the assistant again in this chat to continue."
        )
    # An empty model is legitimate (a provider whose catalog is empty records ""); a missing
    # or non-string value is not.
    if (
        "model" not in record
        or not isinstance(model, str)
        or (model != "" and not model.strip())
        or len(model) > 200
        or not model.isprintable()
    ):
        raise ApprovalResumeIdentityError(
            "The approval does not record a valid AI model. The approved action "
            "already ran; ask the assistant again in this chat to continue."
        )
    return provider, model


def _common(
    record: dict[str, Any],
    approval: pending_approvals.PendingApproval,
    pending_id: str,
) -> dict[str, Any]:
    locale = record.get("locale")
    return {
        "turn_id": record.get("turn_id") or uuid.uuid4().hex,
        "request_id": record.get("request_id") or uuid.uuid4().hex,
        "workspace_generation": approval.context_generation,
        "approval_pending_id": pending_id,
        **{
            key: record[key]
            for key in ("workspace_root", "provider", "model")
            if key in record
        },
        "locale": locale if locale in ("ko", "en") else "ko",
    }


def _has_record(
    records: list[dict[str, Any]], pending_id: str, *, record: str, event_type: str = ""
) -> bool:
    return any(
        item.get("approval_pending_id") == pending_id
        and item.get("record") == record
        and (not event_type or item.get("type") == event_type)
        for item in records
    )


def _talked_since_call(records: list[dict[str, Any]], call_id: str) -> bool:
    """True when a user or assistant message was recorded after the approved call."""
    seen = False
    for record in records:
        kind = record.get("record")
        if kind == "assistant" and any(
            isinstance(call, dict) and call.get("call_id") == call_id
            for call in record.get("tool_calls") or ()
        ):
            seen = True
        elif kind == "event" and record.get("type") == "tool_call" and record.get("call_id") == call_id:
            seen = True
        elif seen and kind in ("user", "assistant"):
            return True
    return False


def _has_call_result(records: list[dict[str, Any]], call_id: str) -> bool:
    """Any answer to this call counts, whoever wrote it (the heal has no pending id)."""
    return any(
        item.get("record") == "event"
        and item.get("type") == "tool_result"
        and item.get("call_id") == call_id
        for item in records
    )


def _approval_receipt(
    pending_id: str,
    outcome: pending_approvals.CompletedApproval,
    common: dict[str, Any],
    *,
    state: str = "resume_pending",
) -> dict[str, Any]:
    approval = outcome.approval
    terminal = state in {"completed", "uncertain"}
    return {
        "record": "approval",
        **common,
        "pending_id": pending_id,
        "name": approval.action_kind,
        "call_id": approval.call_id,
        "args": approval.args,
        "result": outcome.result,
        "state": state,
        "lifecycle": state if terminal else "finalizing",
        "resume_allowed": not terminal,
    }


async def resume(
    *,
    pending_id: str,
    session_id: str,
    call_id: str,
    context_generation: int,
    event_sink: EventSink | None = None,
) -> dict[str, Any]:
    async with session_single_flight(session_id):
        outcome, acquired = pending_approvals.begin_resume(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=context_generation,
        )
        if not acquired:
            state = outcome.resume_state
            return {
                "state": state if state in {"resumed", "uncertain"} else "resume_pending",
                "result": outcome.result,
                "resume_allowed": state == "pending",
                "events": [],
            }

        generation_started = False
        common: dict[str, Any] = {}
        try:
            records = history.read(session_id)
            pending_record = _pending_record(records, pending_id)
            common = _common(pending_record, outcome.approval, pending_id)
            if _has_record(records, pending_id, record="assistant"):
                history.append(
                    session_id,
                    _approval_receipt(
                        pending_id, outcome, common, state="completed"
                    ),
                )
                if not _has_record(records, pending_id, record="terminal"):
                    history.append(
                        session_id,
                        {"record": "terminal", "state": "completed", **common},
                    )
                pending_approvals.finish_resume(pending_id, True)
                return {"state": "resumed", "result": outcome.result, "events": []}
            if outcome.audit_state != "persisted":
                history.append(session_id, _approval_receipt(pending_id, outcome, common))
                outcome = pending_approvals.mark_audit(pending_id, True)
                records = history.read(session_id)

            provider, model = original_identity(pending_record)
            # The recorded model may have been rejected since the approval was
            # created; start from a supported one instead of burning a 400.
            # No notice: the resume stream has no truthful place for it, and
            # the next chat turn re-resolves and announces on its own.
            model = chat.steer_past_rejected_model(provider, model, announce=False)
            client = chat.build_client(provider, model, "")
            if client is None:
                raise ApprovalResumeError(
                    f"The original AI provider '{provider}' is not connected. Reconnect it and "
                    "retry; no other provider will receive this conversation."
                )
            if not _has_call_result(records, outcome.approval.call_id):
                history.append(
                    session_id,
                    {
                        "record": "event",
                        "type": "tool_result",
                        "record_id": history.tool_result_record_id(outcome.approval.call_id),
                        "name": outcome.approval.action_kind,
                        "call_id": outcome.approval.call_id,
                        "result": outcome.result,
                        **common,
                    },
                )
                records = history.read(session_id)
            # Rebuilt after the result is stored, so replay places it right after its call
            # even when the user typed a message while the approval card waited.
            conversation = chat_replay.rebuild_conversation(client, model, records)
            if _talked_since_call(records, outcome.approval.call_id):
                # The result was replayed next to its call, so the conversation would end on
                # the reply to what the user typed meanwhile; say what changed instead.
                conversation.add_nudge(
                    f"I approved the waiting action ({outcome.approval.action_kind}). "
                    "Its result is in the tool result for that call above. Continue from it."
                )
            dispatched = {
                "type": "tool_result",
                "data": {
                    "name": outcome.approval.action_kind,
                    "call_id": outcome.approval.call_id,
                    "result": outcome.result,
                    "state": "dispatched",
                },
            }
            await _emit(event_sink, dispatched)
            generation_started = True
            events = await approval_event_persistence.persist_runtime_events(
                client, model, conversation, session_id, common, event_sink
            )
            history.append(
                session_id,
                _approval_receipt(pending_id, outcome, common, state="completed"),
            )
            if events and events[-1]["type"] == "done":
                await _emit(event_sink, events[-1])
        except ApprovalResumeIdentityError:
            # Permanent: seal the continuation without ever contacting a provider, and
            # record it so a reloaded history does not offer a continuation that cannot run.
            pending_approvals.finish_resume(pending_id, None)
            if common:
                try:
                    history.append(
                        session_id,
                        _approval_receipt(pending_id, outcome, common, state="uncertain"),
                    )
                except (OSError, ValueError):
                    pass
            raise
        except Exception:
            pending_approvals.finish_resume(
                pending_id, None if generation_started else False
            )
            if generation_started and common:
                try:
                    history.append(
                        session_id,
                        _approval_receipt(
                            pending_id, outcome, common, state="uncertain"
                        ),
                    )
                except (OSError, ValueError):
                    pass
            raise
        pending_approvals.finish_resume(pending_id, True)
        return {
            "state": "resumed",
            "result": outcome.result,
            "events": [
                dispatched,
                *events,
            ],
        }
