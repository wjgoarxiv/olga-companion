"""Persist and stream one provider continuation after approved dispatch."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from . import chat, history, pending_approvals, runtime, tools
from .tool_validation import ToolError

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class ApprovalContinuationError(RuntimeError):
    pass


async def persist_runtime_events(
    client: Any,
    model: str,
    conversation: Any,
    session_id: str,
    common: dict[str, Any],
    event_sink: EventSink | None,
) -> list[dict[str, Any]]:
    pending_text = ""
    announced_unfollowed = False
    registered_actions: set[str] = set()
    showed_output = False
    streamed: list[dict[str, Any]] = []
    generation = common.get("workspace_generation")
    language = common.get("locale")
    if language not in ("ko", "en"):
        language = "ko"
    async for event in runtime.run_turn(
        client,
        "",
        model=model,
        conversation=conversation,
        seed_user=False,
        context_generation=generation if isinstance(generation, int) else None,
        fill_active_case=False,
        locale=language,
    ):
        streamed.append({"type": event.type, "data": event.data})
        if event.type in ("tool_call", "approval_required", "error") or (
            event.type == "text" and str(event.data.get("text") or "").strip()
        ):
            showed_output = True
        elif event.type == "tool_result":
            # A tool card is not an answer; the turn still owes the user a reply after it.
            showed_output = False
        if event.type == "text":
            pending_text = str(event.data.get("text", ""))
            announced_unfollowed = chat._announces_save_step(pending_text)
        elif event.type == "tool_call":
            announced_unfollowed = False
            batch = event.data.get("tool_calls")
            if batch:
                history.append(
                    session_id,
                    {
                        "record": "assistant",
                        "text": pending_text,
                        "tool_calls": batch,
                        "thought_signature": event.data.get("thought_signature"),
                        **common,
                    },
                )
                pending_text = ""
            history.append(
                session_id,
                {
                    "record": "event",
                    "type": "tool_call",
                    **{
                        key: event.data.get(key)
                        for key in ("name", "call_id", "args", "raw_arguments", "item_id")
                    },
                    **common,
                },
            )
        elif event.type == "tool_result":
            history.append(
                session_id,
                {
                    "record": "event",
                    "type": "tool_result",
                    **{
                        key: event.data.get(key)
                        for key in ("name", "call_id", "result")
                    },
                    **common,
                },
            )
        elif event.type == "approval_required":
            try:
                display = tools.approval_display(
                    str(event.data["name"]),
                    dict(event.data["args"]),
                    locale=language,
                )
            except ToolError:
                display = {}
            registered_actions.add(str(event.data.get("name", "")))
            next_pending = pending_approvals.register(
                action_kind=str(event.data["name"]),
                args=dict(event.data["args"]),
                call_id=str(event.data["call_id"]),
                context_generation=int(event.data["context_generation"]),
                session_id=session_id,
            )
            event = runtime.AgentEvent(
                event.type,
                {
                    **event.data,
                    "pending_id": next_pending,
                    "display": display,
                    "expires_at": pending_approvals.registered_expires_epoch(next_pending),
                },
            )
            streamed[-1] = {"type": event.type, "data": event.data}
            history.append(
                session_id,
                {
                    "record": "approval",
                    "pending_id": next_pending,
                    "display": display,
                    "state": "pending",
                    "lifecycle": "awaiting-approval",
                    **event.data,
                    **common,
                },
            )
        elif event.type == "error":
            history.append(
                session_id,
                {"record": "error", "message": event.data.get("message"), **common},
            )
        elif event.type == "done":
            original = str(event.data.get("text", ""))
            text = chat.guard_turn_text(
                original,
                announced_unfollowed=announced_unfollowed,
                registered_actions=registered_actions,
            )
            if not text.strip() and not showed_output:
                text = chat.EMPTY_REPLY_NOTICE_EN if language == "en" else chat.EMPTY_REPLY_NOTICE
            if text != original:
                event = runtime.AgentEvent(event.type, {**event.data, "text": text})
                streamed[-1] = {"type": event.type, "data": event.data}
            if text:
                history.append(
                    session_id, {"record": "assistant", "text": text, **common}
                )
            history.append(
                session_id, {"record": "terminal", "state": "completed", **common}
            )
        if event.type != "done" and event_sink is not None:
            await event_sink(streamed[-1])
        if event.type == "error":
            raise ApprovalContinuationError("Provider continuation failed.")
    return streamed
