"""Provider-neutral reconstruction of a Chat conversation."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal, assert_never

from ..llm.protocol import ApiClient, ConversationBuilder, ToolCall

RecordTag = Literal[
    "approval", "artifact", "assistant", "error", "event", "meta", "terminal", "tombstone", "user"
]
EventTag = Literal["tool_call", "tool_result"]
_RECORD_TAGS: Final[dict[str, RecordTag]] = {
    tag: tag
    for tag in (
        "approval", "artifact", "assistant", "error", "event", "meta", "terminal", "tombstone", "user"
    )
}
_EVENT_TAGS: Final[dict[str, EventTag]] = {
    "tool_call": "tool_call",
    "tool_result": "tool_result",
}


class ChatReplayIntegrityError(ValueError):
    """Persisted provider evidence is intentionally not replayable."""


def rebuild_conversation(
    client: ApiClient,
    model: str,
    records: Sequence[Mapping[str, Any]],
) -> ConversationBuilder:
    """Replay canonical records into a fresh provider conversation builder.

    Providers require each tool call to be answered right after it, once per call id.
    The persisted order can differ: a user may type while an approval card waits, so a
    result can land after that message, or not exist yet. Each call's result is therefore
    replayed next to its call, and a call with no result gets a short placeholder.
    """
    conversation = client.create_conversation(model)
    results = _first_results(records)
    approval_states: dict[str, str] = {}
    for record in records:
        if record.get("record") == "approval" and record.get("state") and record.get("call_id"):
            approval_states[str(record["call_id"])] = str(record["state"])
    awaiting = {call_id for call_id, state in approval_states.items() if state == "pending"}
    replayed_call_ids: set[str] = set()
    answered: set[str] = set()
    for record in records:
        tag = _RECORD_TAGS.get(str(record.get("record", "")))
        if tag is None:
            continue
        match tag:
            case "user":
                conversation.add_user_message(str(record.get("text", "")))
            case "assistant":
                if record.get("replay_blocked"):
                    raise ChatReplayIntegrityError(
                        "Cannot replay oversized assistant tool evidence safely."
                    )
                calls = _tool_calls(record.get("tool_calls"))
                conversation.add_assistant_response(
                    str(record.get("text", "")),
                    calls or None,
                    record.get("thought_signature"),
                )
                replayed_call_ids.update(call.call_id for call in calls)
                _answer(conversation, calls, results, awaiting, answered)
            case "event":
                _replay_event(conversation, record, replayed_call_ids, results, awaiting, answered)
            case "meta" | "approval" | "artifact" | "error" | "terminal" | "tombstone":
                continue
            case unreachable:
                assert_never(unreachable)
    return conversation


def _first_results(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    results: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if record.get("record") == "event" and record.get("type") == "tool_result":
            results.setdefault(str(record.get("call_id", "")), record)
    return results


def _answer(
    conversation: ConversationBuilder,
    calls: Sequence[ToolCall],
    results: Mapping[str, Mapping[str, Any]],
    awaiting: set[str],
    answered: set[str],
) -> None:
    for call in calls:
        if call.call_id in answered:
            continue
        answered.add(call.call_id)
        found = results.get(call.call_id)
        if found is not None:
            payload: Any = found.get("result")
        elif call.call_id in awaiting:
            payload = {
                "state": "awaiting_approval",
                "note": "No result yet: this action waits for the user's approval card. "
                "Do not call it again; the user approves or rejects it on the card.",
            }
        else:
            payload = {
                "state": "no_result",
                "note": "This call has no recorded result; it was interrupted. Do not assume it ran.",
            }
        conversation.add_tool_result(
            call.call_id, call.name, json.dumps(payload, ensure_ascii=False, default=str)
        )


def _replay_event(
    conversation: ConversationBuilder,
    record: Mapping[str, Any],
    replayed_call_ids: set[str],
    results: Mapping[str, Mapping[str, Any]],
    awaiting: set[str],
    answered: set[str],
) -> None:
    tag = _EVENT_TAGS.get(str(record.get("type", "")))
    if tag is None:
        return
    match tag:
        case "tool_call":
            call_id = str(record.get("call_id", ""))
            if call_id in replayed_call_ids:
                return
            replayed_call_ids.add(call_id)
            call = ToolCall(
                name=str(record.get("name", "")),
                args=dict(record.get("args") or {}),
                call_id=call_id,
                raw_arguments=str(record.get("raw_arguments", "")),
                item_id=str(record.get("item_id", "")),
            )
            conversation.add_assistant_response(
                str(record.get("assistant_text", "")), [call]
            )
            _answer(conversation, [call], results, awaiting, answered)
        case "tool_result":
            call_id = str(record.get("call_id", ""))
            if call_id in answered:
                return  # already replayed right after its call
            # A result whose call was never recorded replays where it stands, as before.
            conversation.add_tool_result(
                call_id,
                str(record.get("name", "")),
                json.dumps(record.get("result"), ensure_ascii=False, default=str),
            )
        case unreachable:
            assert_never(unreachable)


def _tool_calls(value: Any) -> list[ToolCall]:
    if not value:
        return []
    return [
        ToolCall(
            name=str(raw.get("name", "")),
            args=dict(raw.get("args") or {}),
            call_id=str(raw.get("call_id", "")),
            raw_arguments=str(raw.get("raw_arguments", "")),
            item_id=str(raw.get("item_id", "")),
        )
        for raw in value
    ]
