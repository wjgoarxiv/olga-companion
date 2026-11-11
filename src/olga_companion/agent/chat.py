"""Chat orchestration seam (T3).

Bridges the HTTP layer to the agent runtime: resolves a provider selection into a
concrete ApiClient (from stored OAuth tokens), runs a turn, and persists records
to the session history. The client-construction seam is overridable so the SSE
spine can be tested offline with a scripted FakeApiClient — the real provider
wiring is exercised live in T5.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, Final, Literal, assert_never

from .. import workspace
from ..llm import factory
from . import chat_replay, history, pending_approvals, plan_model, plan_progress, runtime, tools
from .chat_singleflight import session_busy, session_single_flight
from .history_policy import opaque_path_identity
from .tool_validation import ToolError

# Test/DI seam: default builds a real provider ApiClient; tests replace it.
_client_builder: Callable[[str, str, str], Any] | None = None

_PROVIDER_LABELS = {
    "openai": "OpenAI (Codex)",
    "copilot": "GitHub Copilot",
    "antigravity": "Antigravity (Gemini)",
    "xai": "xAI (Grok)",
    "apikey": "API 키",
}

FALSE_APPROVAL_NOTICE = "승인 요청이 아직 만들어지지 않았습니다. 저장하려면 다시 요청하세요."
FALSE_APPROVAL_NOTICE_EN = "The approval request has not been created yet. Ask again to save."
ANNOUNCED_STEP_NOTICE = "다음 단계가 아직 실행되지 않았습니다. '계속'이라고 보내면 이어서 진행합니다."
ANNOUNCED_STEP_NOTICE_EN = "The next step has not run yet. Reply 'continue' to proceed."
EMPTY_REPLY_NOTICE = "AI가 빈 답을 보냈습니다. 같은 요청을 다시 보내 주세요."
EMPTY_REPLY_NOTICE_EN = "The AI sent an empty reply. Send the request again."
DELETED_SESSION_NOTICE = "삭제된 채팅 세션입니다."
DELETED_SESSION_NOTICE_EN = "This Chat session has been deleted."
_CARD_PHRASES = ("승인 카드", "approval card")
_CLAIM_PHRASES = ("올려", "raised", "waiting")
_ANNOUNCE_VERBS = ("올리겠습니다", "요청하겠습니다", "만들겠습니다")
_ANNOUNCE_NOUNS = ("승인", "저장", "계획")
_EN_PROMISES = ("i'll request", "i'll create", "i'll raise")
_EN_NOUNS = ("approval", "plan", "save")
_WAITS_ON_USER = (
    "?", "？", "주시면", "수락하시면", "확인해 주세요", "once you confirm", "once you reply", "let me know",
)

EventKind = Literal[
    "approval_required", "done", "error", "text", "thinking", "tool_call", "tool_result"
]
_EVENT_KINDS: Final[dict[str, EventKind]] = {
    kind: kind
    for kind in (
        "approval_required", "done", "error", "text", "thinking", "tool_call", "tool_result"
    )
}


def _unreviewable_plan(display: dict[str, Any]) -> str:
    """Why a plan card cannot be offered: the server reviewed no step of it."""
    plan = display.get("plan")
    rows = plan.get("steps") if isinstance(plan, dict) else None
    if isinstance(rows, list) and rows:
        return ""
    return "The plan has no reviewed steps, so no approval card was raised. Ask for it again."


def _claims_approval_card(text: str) -> bool:
    """A card phrase plus a raised/waiting verb, not a plain explanation."""
    folded = text.casefold()
    has_card = any(phrase.casefold() in folded for phrase in _CARD_PHRASES)
    has_claim = any(phrase.casefold() in folded for phrase in _CLAIM_PHRASES)
    return has_card and has_claim


def guard_turn_text(
    text: str,
    *,
    announced_unfollowed: bool,
    registered_actions: set[str],
    locale: str = "ko",
) -> str:
    """Append a notice only when this turn itself did not register the approval."""
    false_notice = FALSE_APPROVAL_NOTICE_EN if locale == "en" else FALSE_APPROVAL_NOTICE
    step_notice = ANNOUNCED_STEP_NOTICE_EN if locale == "en" else ANNOUNCED_STEP_NOTICE
    original = text
    if original and _claims_approval_card(original) and not registered_actions:
        text = f"{text}\n\n{false_notice}"
    if (
        original
        and announced_unfollowed
        and _announces_save_step(original)
        and "case_publish" not in registered_actions
    ):
        text = f"{text}\n\n{step_notice}"
    return text


def _announces_save_step(text: str) -> bool:
    """A future save or approval promise, not a past claim or a plain explanation.

    A turn that asks the user for a value or a yes is waiting on them, not stalled:
    its promise is conditional on the answer, so it gets no continue line.
    """
    folded_all = text.casefold()
    if any(marker in folded_all for marker in _WAITS_ON_USER):
        return False
    has_verb = any(verb in text for verb in _ANNOUNCE_VERBS)
    has_noun = any(noun in text for noun in _ANNOUNCE_NOUNS)
    if has_verb and has_noun:
        return True
    folded = text.casefold().replace("\u2019", "'")
    return any(phrase in folded for phrase in _EN_PROMISES) and any(
        noun in folded for noun in _EN_NOUNS
    )


def set_client_builder(builder: Callable[[str, str, str], Any] | None) -> None:
    global _client_builder
    _client_builder = builder


def _build_real_client(provider: str, model: str, variant: str) -> Any:
    """Construct a tool-calling ApiClient from stored OAuth tokens.

    Returns None when the provider has no usable credentials — the caller surfaces
    an honest "connect this provider first" error rather than a crash.

    openai builds the real `OpenAIResponsesApiClient` from the Codex CLI OAuth
    (`~/.codex/auth.json`) so the agent runtime can actually drive tool calls —
    the preview (string→string) client is the wrong protocol for `run_turn`.
    """
    from ..llm import agent_clients, codex_oauth, copilot_clients, xai_oauth

    try:
        if provider == "openai":
            return copilot_clients.build_openai_agent_client_from_codex(model=model, variant=variant)
        if provider == "copilot":
            return agent_clients.build_copilot_agent_client_from_env()
        if provider == "antigravity":
            return agent_clients.build_antigravity_agent_client_from_env()
        if provider == "xai":
            return xai_oauth.build_responses_client()
        if provider == "apikey":
            from ..llm.api_key_connections import build_agent_client

            return build_agent_client(model)
    except (codex_oauth.CodexAuthError, RuntimeError):
        return None
    return None


def build_client(provider: str, model: str, variant: str) -> Any:
    builder = _client_builder or _build_real_client
    return builder(provider, model, variant)


_HEAL_EXPIRED_KO = "승인 시간이 지났습니다. 다시 요청하세요."
_HEAL_EXPIRED_EN = "The approval expired. Request it again."
_HEAL_UNCONFIRMED = "The approved action's outcome could not be confirmed."
_HEAL_IDENTITY_KEYS = (
    "turn_id",
    "request_id",
    "workspace_root",
    "provider",
    "model",
    "locale",
)


def _live_generation() -> int | None:
    try:
        return workspace.context_generation()
    except workspace.WorkspaceError:
        return None


def _dead_call_answer(
    session_id: str,
    approval: dict[str, Any],
    call_id: str,
    generation: int | None,
    language: str,
) -> dict[str, Any] | None:
    """What to tell the model about a call whose approval can no longer progress.

    None means the approval is still owned by its card or its continuation.
    """
    state = approval.get("state")
    if state == "rejected":
        return {"error": "Rejected by the user."}
    if state == "failed":
        result = approval.get("result")
        return {
            "error": str(approval.get("reason") or "")
            or (str(result.get("error") or "") if isinstance(result, dict) else "")
            or "The approved action failed before dispatch."
        }
    if state not in {"pending", "resume_pending", "uncertain"}:
        return None
    pending_id = str(approval.get("pending_id", ""))
    recorded = approval.get("workspace_generation")
    moved = generation is not None and recorded != generation
    try:
        outcome = pending_approvals.recover(
            pending_id,
            session_id=session_id,
            call_id=call_id,
            context_generation=recorded,
        )
    except (TypeError, ValueError):
        outcome = None
    match outcome:
        case pending_approvals.CompletedApproval():
            # The action ran. Its continuation answers the call unless that can no
            # longer happen: it ended uncertain, or the workspace moved on.
            if outcome.resume_state == "uncertain" or moved:
                return dict(outcome.result)
            return None
        case pending_approvals.FailedApproval(message=message):
            steps = (
                plan_progress.report(pending_id)
                if approval.get("name") == plan_model.PLAN_KIND
                else []
            )
            return {"error": message, "steps": steps} if steps else {"error": message}
        case pending_approvals.RejectedApproval():
            return {"error": "Rejected by the user."}
        case None:
            pass
    if state == "pending":
        try:
            actionable = pending_approvals.is_actionable(
                pending_id,
                session_id=session_id,
                call_id=call_id,
                context_generation=recorded,
                current_generation=generation,
            )
        except (TypeError, ValueError):
            actionable = False
        if actionable:
            return None
        return {"error": _HEAL_EXPIRED_EN if language == "en" else _HEAL_EXPIRED_KO}
    stored = approval.get("result")
    return dict(stored) if isinstance(stored, dict) else {"error": _HEAL_UNCONFIRMED}


def _heal_orphan_tool_calls(
    session_id: str,
    records: list[dict[str, Any]],
    language: str,
    *,
    generation: int | None = None,
) -> bool:
    """Answer model calls stranded by a dead approval before replay.

    Returns True when history gained a `tool_result`, so the caller rebuilds
    the provider conversation from the healed records. Approvals that are
    still actionable stay owned by their card and are left alone.
    """
    answered: set[str] = set()
    approvals_by_call: dict[str, dict[str, Any]] = {}
    stranded: dict[str, str] = {}
    for record in records:
        tag = record.get("record")
        if tag == "event" and record.get("type") == "tool_result":
            answered.add(str(record.get("call_id", "")))
        elif tag == "approval":
            approvals_by_call[str(record.get("call_id", ""))] = record
        elif tag == "assistant":
            for call in record.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("call_id"):
                    stranded.setdefault(str(call["call_id"]), str(call.get("name", "")))
        elif tag == "event" and record.get("type") == "tool_call":
            if record.get("call_id"):
                stranded.setdefault(str(record["call_id"]), str(record.get("name", "")))
    if generation is None:
        generation = _live_generation()
    healed = False
    for call_id, name in stranded.items():
        if call_id in answered:
            continue
        approval = approvals_by_call.get(call_id)
        if approval is None:
            continue
        answer = _dead_call_answer(session_id, approval, call_id, generation, language)
        if answer is None:
            continue
        envelope = {
            key: approval[key] for key in _HEAL_IDENTITY_KEYS if key in approval
        }
        try:
            history.append(
                session_id,
                {
                    "record": "event",
                    "type": "tool_result",
                    "record_id": history.tool_result_record_id(call_id),
                    "name": name or str(approval.get("name", "")),
                    "call_id": call_id,
                    "result": tools._cap(answer),
                    **envelope,
                },
            )
        except (OSError, ValueError):
            continue
        healed = True
    return healed


def resolve_selection(headers: dict[str, str] | None, settings: dict[str, Any] | None):
    return factory.resolve_llm_selection(headers, settings)


async def run_chat_turn(
    session_id: str,
    user_message: str,
    *,
    provider: str,
    model: str,
    variant: str,
    locale: str = "ko",
) -> AsyncIterator[runtime.AgentEvent]:
    """Run one turn and persist records; yields the same AgentEvents for streaming.

    Persisted records never include provider credentials (history.append refuses
    credential-keyed records defensively).
    """
    if session_busy(session_id):
        yield runtime.AgentEvent("phase", {"phase": "queued"})
    async with session_single_flight(session_id):
        async for event in _run_locked_turn(
            session_id,
            user_message,
            provider=provider,
            model=model,
            variant=variant,
            locale=locale,
        ):
            yield event


async def _run_locked_turn(
    session_id: str,
    user_message: str,
    *,
    provider: str,
    model: str,
    variant: str,
    locale: str = "ko",
) -> AsyncIterator[runtime.AgentEvent]:
    records = history.read(session_id)
    language = locale if locale in runtime.LOCALES else "ko"
    if records and records[-1].get("record") == "tombstone":
        notice = DELETED_SESSION_NOTICE_EN if language == "en" else DELETED_SESSION_NOTICE
        yield runtime.AgentEvent("error", {"message": notice})
        return
    turn_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    root, generation = workspace.context_identity()
    common = {
        "turn_id": turn_id,
        "request_id": request_id,
        "workspace_generation": generation,
        "workspace_root": opaque_path_identity(str(root)),
        "provider": provider,
        "model": model,
        "locale": language,
    }
    # Heal before the user message: replay must end with the answered call, then
    # exactly one copy of this message, which `run_turn` seeds itself.
    if _heal_orphan_tool_calls(session_id, records, language, generation=generation):
        records = history.read(session_id)
    client = build_client(provider, model, variant)
    history.append(session_id, {"record": "user", "text": user_message, **common})
    if client is None:
        label = _PROVIDER_LABELS.get(provider, provider)
        if language == "en":
            message = (
                f"The selected AI provider ({label}) is not connected. "
                "Choose a connected provider in Settings → AI provider."
            )
        else:
            message = (
                f"선택한 AI 공급자({label})가 연결되어 있지 않습니다. "
                "설정 → AI 공급자에서 연결된 공급자를 고르세요."
            )
        history.append(session_id, {"record": "error", "message": message, **common})
        yield runtime.AgentEvent("error", {"message": message})
        return

    conversation = chat_replay.rebuild_conversation(client, model, records)
    yield runtime.AgentEvent("phase", {"phase": "model"})
    pending_text = ""
    announced_unfollowed = False
    registered_actions: set[str] = set()
    showed_output = False
    async for original in runtime.run_turn(
        client,
        user_message,
        model=model,
        conversation=conversation,
        context_generation=generation,
        locale=language,
        stream_draft=True,
    ):
        event = original
        kind = _EVENT_KINDS.get(event.type)
        if kind is None:
            yield event
            continue
        if kind in ("tool_call", "approval_required", "error") or (
            kind == "text" and str(event.data.get("text") or "").strip()
        ):
            showed_output = True
        elif kind == "tool_result":
            # A tool card is not an answer; the turn still owes the user a reply after it.
            showed_output = False
        match kind:
            case "text":
                pending_text = str(event.data.get("text", ""))
                announced_unfollowed = _announces_save_step(pending_text)
            case "approval_required":
                is_plan = event.data["name"] == plan_model.PLAN_KIND
                try:
                    display = tools.approval_display(
                        str(event.data["name"]),
                        dict(event.data["args"]),
                        locale=language,
                    )
                    refusal = _unreviewable_plan(display) if is_plan else ""
                except ToolError as exc:
                    # Preserve the existing approval/error lifecycle for a stale or
                    # synthetic selection, but never substitute model-authored facts.
                    display = {}
                    refusal = str(exc)
                if is_plan and refusal:
                    # A plan with nothing reviewed to show is answered, never offered.
                    answer = tools._cap({"error": refusal})
                    history.append(
                        session_id,
                        {
                            "record": "event",
                            "type": "tool_result",
                            "name": event.data.get("name"),
                            "call_id": event.data.get("call_id"),
                            "result": answer,
                            **common,
                        },
                    )
                    yield runtime.AgentEvent(
                        "tool_result",
                        {"name": event.data.get("name"), "call_id": event.data.get("call_id"), "result": answer},
                    )
                    history.append(session_id, {"record": "terminal", "state": "completed", **common})
                    yield runtime.AgentEvent("done", {"text": ""})
                    return
                pending_id = pending_approvals.register(
                    action_kind=str(event.data["name"]),
                    args=dict(event.data["args"]),
                    call_id=str(event.data["call_id"]),
                    context_generation=event.data["context_generation"],
                    session_id=session_id,
                )
                expires_at = pending_approvals.registered_expires_epoch(pending_id)
                registered_actions.add(str(event.data.get("name", "")))
                event = runtime.AgentEvent(
                    event.type,
                    {
                        **event.data,
                        "pending_id": pending_id,
                        "display": display,
                        "expires_at": expires_at,
                    },
                )
                history.append(
                    session_id,
                    {
                        "record": "approval",
                        "pending_id": pending_id,
                        "call_id": event.data.get("call_id"),
                        "name": event.data.get("name"),
                        "args": event.data.get("args"),
                        "display": display,
                        "expires_at": expires_at,
                        "state": "pending",
                        "lifecycle": "awaiting-approval",
                        **common,
                    },
                )
            case "tool_call":
                announced_unfollowed = False
                batch = event.data.get("tool_calls")
                if batch:
                    history.append(
                        session_id,
                        {
                            "record": "assistant",
                            "text": pending_text,
                            "tool_calls": batch,
                            "thought_signature": event.data.get(
                                "thought_signature"
                            ),
                            **common,
                        },
                    )
                history.append(
                    session_id,
                    {
                        "record": "event",
                        "type": "tool_call",
                        "name": event.data.get("name"),
                        "call_id": event.data.get("call_id"),
                        "args": event.data.get("args"),
                        "raw_arguments": event.data.get("raw_arguments"),
                        "item_id": event.data.get("item_id"),
                        **common,
                    },
                )
                if batch:
                    pending_text = ""
            case "tool_result":
                history.append(
                    session_id,
                    {
                        "record": "event",
                        "type": "tool_result",
                        "name": event.data.get("name"),
                        "call_id": event.data.get("call_id"),
                        "result": event.data.get("result"),
                        **common,
                    },
                )
            case "error":
                history.append(
                    session_id,
                    {
                        "record": "error",
                        "message": event.data.get("message"),
                        **common,
                    },
                )
            case "done":
                original = str(event.data.get("text", ""))
                text = guard_turn_text(
                    original,
                    announced_unfollowed=announced_unfollowed,
                    registered_actions=registered_actions,
                    locale=language,
                )
                if not text.strip() and not showed_output:
                    # The provider answered with nothing at all; say so, never stay silent.
                    text = EMPTY_REPLY_NOTICE_EN if language == "en" else EMPTY_REPLY_NOTICE
                if text != original:
                    event = runtime.AgentEvent(event.type, {**event.data, "text": text})
                if text:
                    history.append(
                        session_id,
                        {"record": "assistant", "text": text, **common},
                    )
                history.append(
                    session_id,
                    {"record": "terminal", "state": "completed", **common},
                )
            case "thinking":
                pass
            case unreachable:
                assert_never(unreachable)
        yield event
