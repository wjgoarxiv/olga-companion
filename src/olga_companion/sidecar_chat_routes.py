from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .runtime_logging import LOGGER_NAME
from .agent.approval_execution import (
    EXECUTING_SENTENCE,
    INACTIVE_SENTENCE,
    USED_SENTENCE,
)
from .agent.pending_approvals import (
    ApprovalClaimInactiveError,
    ApprovalExecutingError,
    ApprovalUnavailableError,
)
from .sidecar_contracts import (
    ApprovalExecuteRequest,
    ApprovalRejectRequest,
    ChatRequest,
    ChatResponseStopRequest,
    NewSessionRequest,
)


router = APIRouter()


def _resume_error(state: str, resume_allowed: bool, reason: str = "") -> dict[str, Any]:
    return {
        "state": state,
        "resume_allowed": resume_allowed,
        "inspection_only": state == "uncertain",
        "message": reason or (
            "Approval continuation requires recovery inspection."
            if state == "uncertain"
            else "Approval continuation is still pending."
        ),
    }


def _facade() -> Any:
    from . import sidecar

    return sidecar


@router.get("/api/session/token")
def api_session_token() -> dict[str, str]:
    """Return the no-store boot token used to harden the loopback sidecar."""
    return {"token": _facade().session_token.boot_token()}


@router.get("/api/providers")
def api_providers() -> dict[str, Any]:
    sidecar = _facade()
    providers = []
    for name in sidecar.llm_catalog.PROVIDER_ORDER:
        models = sidecar.llm_catalog.available_models(name, cache_only=True)
        if name == "apikey":
            models = [{"id": item["id"], "label": item["label"]} for item in models]
        providers.append(
            {
                "provider": name,
                "known": sidecar.llm_catalog.is_known_provider(name),
                "models": models,
                "has_catalog": bool(models),
                "connected": sidecar.llm_catalog.is_connected(name),
                "login": sidecar.llm_catalog.provider_login(name),
            }
        )
    return {"providers": providers}


@router.get("/api/llm-selection")
def api_llm_selection_get(x_session_token: str | None = Header(default=None)) -> dict[str, str]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    from . import config
    from .llm import factory as llm_factory

    selection = config.load_llm_selection()
    if selection["provider"]:
        return selection
    connected_default = llm_factory.default_connected_selection()
    if connected_default is None:
        return selection
    provider, model, variant = connected_default
    return {"provider": provider, "model": model, "variant": variant}


@router.put("/api/llm-selection")
async def api_llm_selection_put(
    http_request: Request,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    from . import config

    try:
        record = await http_request.json()
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail="LLM selection must be an object.") from exc
    try:
        return config.save_llm_selection(record)
    except config.LlmSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/providers/xai/login")
def api_xai_login(x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    from .llm import xai_oauth

    try:
        return xai_oauth.start_login()
    except xai_oauth.XaiAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/providers/xai/login/status")
def api_xai_login_status(x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    _facade()._require_session_token(x_session_token)
    from .llm import xai_oauth

    return xai_oauth.login_status()


@router.post("/api/providers/xai/logout")
def api_xai_logout(x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    _facade()._require_session_token(x_session_token)
    from .llm import xai_oauth

    return xai_oauth.logout()


@router.get("/api/providers/apikey")
def api_apikey_list(x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    _facade()._require_session_token(x_session_token)
    from .llm import api_key_connections as keys

    return {"connections": keys.list_connections()}


@router.post("/api/providers/apikey")
async def api_apikey_create(
    http_request: Request,
    x_session_token: str | None = Header(default=None),
) -> Any:
    _facade()._require_session_token(x_session_token)
    from .llm import api_key_connections as keys

    try:
        payload = await http_request.json()
    except (json.JSONDecodeError, UnicodeError):
        return JSONResponse(status_code=400, content={"outcome": "invalid_label"})
    try:
        return keys.save_connection(payload)
    except keys.ApiKeyRejected as exc:
        return JSONResponse(status_code=400, content={"outcome": exc.outcome})


@router.post("/api/providers/apikey/{connection_id}/verify")
def api_apikey_verify(
    connection_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _facade()._require_session_token(x_session_token)
    from .llm import api_key_connections as keys

    try:
        return keys.verify_connection(connection_id)
    except keys.ApiKeyLookupError as exc:
        raise HTTPException(status_code=404, detail="Unknown API key connection.") from exc


@router.delete("/api/providers/apikey/{connection_id}")
def api_apikey_delete(
    connection_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _facade()._require_session_token(x_session_token)
    from .llm import api_key_connections as keys

    return {"deleted": keys.delete_connection(connection_id)}




def _used_approval_body(exc: BaseException) -> dict[str, Any] | None:
    """A click that never dispatched is a closed refusal, not an uncertain outcome."""
    if isinstance(exc, ApprovalUnavailableError):
        sentence = USED_SENTENCE
    elif isinstance(exc, ApprovalExecutingError):
        sentence = EXECUTING_SENTENCE
    elif isinstance(exc, ApprovalClaimInactiveError):
        sentence = INACTIVE_SENTENCE
    else:
        return None
    return {
        "state": "failed",
        "resume_allowed": False,
        "result": {"ok": False, "code": "approval_unavailable", "error": sentence},
    }


@router.post("/api/approvals/execute")
def api_approvals_execute(
    request: ApprovalExecuteRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        return sidecar.approval_execution.execute(
            pending_id=request.pending_id,
            session_id=request.session_id,
            call_id=request.call_id,
            context_generation=request.context_generation,
        )
    except sidecar.workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sidecar.pending_approvals.PendingApprovalError as exc:
        body = _used_approval_body(exc)
        if body is not None:
            sidecar.approval_execution.answer_unactionable_call(
                session_id=request.session_id,
                pending_id=request.pending_id,
                call_id=request.call_id,
                message=str(body["result"]["error"]),
            )
            return body
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sidecar.approval_execution.ApprovalDispatchUncertainError as exc:
        return JSONResponse(status_code=409, content=exc.response())
    except sidecar.approval_execution.ApprovalRejectedError as exc:
        sidecar.approval_execution.answer_unactionable_call(
            session_id=request.session_id,
            pending_id=request.pending_id,
            call_id=request.call_id,
            message="Rejected by the user.",
        )
        return JSONResponse(status_code=409, content=exc.response())
    except (sidecar.approvals.ApprovalError, sidecar.tools.ToolError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/approvals/resume")
async def api_approvals_resume(
    request: ApprovalExecuteRequest,
    x_session_token: str | None = Header(default=None),
) -> StreamingResponse:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        sidecar.approval_execution.validate_resume(
            pending_id=request.pending_id,
            session_id=request.session_id,
            call_id=request.call_id,
            context_generation=request.context_generation,
        )
    except sidecar.workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        sidecar.pending_approvals.PendingApprovalError,
        sidecar.approval_execution.ApprovalResumeError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def event_stream():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        emitted = False

        async def sink(event: dict[str, Any]) -> None:
            nonlocal emitted
            emitted = True
            await queue.put(event)

        async def produce() -> None:
            try:
                result = await sidecar.approval_execution.resume(
                    pending_id=request.pending_id,
                    session_id=request.session_id,
                    call_id=request.call_id,
                    context_generation=request.context_generation,
                    event_sink=sink,
                )
                if not emitted:
                    terminal = result["state"] == "resumed"
                    await queue.put(
                        {
                            "type": "done" if terminal else "error",
                            "data": {"state": "resumed", "result": result["result"]}
                            if terminal
                            else _resume_error(result["state"], bool(result.get("resume_allowed"))),
                        }
                    )
            except Exception as exc:  # noqa: BLE001  # provider details stay server-side
                # Only our own resume-guard text is user-safe; anything else stays generic.
                reason = str(exc) if isinstance(exc, sidecar.approval_execution.ApprovalResumeError) else ""
                outcome = sidecar.pending_approvals.recover(
                    request.pending_id,
                    session_id=request.session_id,
                    call_id=request.call_id,
                    context_generation=request.context_generation,
                )
                state = "uncertain" if getattr(outcome, "resume_state", "") == "uncertain" else "resume_pending"
                await queue.put({"type": "error", "data": _resume_error(state, state == "resume_pending", reason)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(produce())
        yield (
            "event: open\ndata: "
            f"{json.dumps({'pending_id': request.pending_id, 'state': 'finalizing'})}\n\n"
        )
        while (event := await queue.get()) is not None:
            yield (
                f"event: {event['type']}\ndata: "
                f"{json.dumps(event['data'], default=str)}\n\n"
            )
        await task

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/approvals/reject")
def api_approvals_reject(
    request: ApprovalRejectRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        return sidecar.approval_execution.reject(
            pending_id=request.pending_id,
            session_id=request.session_id,
            call_id=request.call_id,
            context_generation=request.context_generation,
        )
    except sidecar.workspace.StaleWorkspaceContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sidecar.pending_approvals.PendingApprovalError as exc:
        body = _used_approval_body(exc)
        if body is not None:
            sidecar.approval_execution.answer_unactionable_call(
                session_id=request.session_id,
                pending_id=request.pending_id,
                call_id=request.call_id,
                message=str(body["result"]["error"]),
            )
            return body
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/chat/session")
def api_chat_new_session(
    request: NewSessionRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    return {"session_id": sidecar.history.new_session(request.title)}


@router.get("/api/chat/sessions")
def api_chat_sessions() -> dict[str, Any]:
    return {"sessions": _facade().history.list_sessions()}


@router.get("/api/chat/session/{session_id}")
def api_chat_read_session(session_id: str) -> dict[str, Any]:
    sidecar = _facade()
    try:
        records = sidecar.history.read(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        current_generation: int | None = sidecar.workspace.context_generation()
    except sidecar.workspace.WorkspaceError:
        current_generation = None
    for index, record in enumerate(records):
        generation = record.get("workspace_generation")
        if (
            record.get("record") == "approval"
            and record.get("state") == "pending"
            and isinstance(generation, int)
            and not isinstance(generation, bool)
            and sidecar.pending_approvals.is_actionable(
                str(record.get("pending_id", "")),
                session_id=session_id,
                call_id=str(record.get("call_id", "")),
                context_generation=generation,
                current_generation=current_generation,
            )
        ):
            records[index] = {**record, "actionable": True}
    return {"records": records}


@router.delete("/api/chat/session/{session_id}")
def api_chat_delete_session(
    session_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    try:
        removed = sidecar.history.detach(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": removed, "session_id": session_id}


@router.post("/api/chat/response/stop")
def api_chat_stop_response(
    request: ChatResponseStopRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, bool | str]:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    return sidecar.chat_response_control.stop_response(request.session_id)


@router.post("/api/chat")
async def api_chat(
    request: ChatRequest,
    http_request: Request,
    x_session_token: str | None = Header(default=None),
) -> StreamingResponse:
    sidecar = _facade()
    sidecar._require_session_token(x_session_token)
    headers = {key: value for key, value in http_request.headers.items()}
    from . import config

    locale = request.locale or "ko"
    if locale not in ("ko", "en"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_locale",
                "message": "locale must be 'ko' or 'en'.",
            },
        )

    provider, model, variant = sidecar.chat.resolve_selection(
        headers, config.llm_selection_settings()
    )

    async def event_stream():
        async with sidecar.chat_response_control.active_response(request.session_id):
            yield (
                f"event: open\ndata: "
                f"{json.dumps({'provider': provider, 'model': model})}\n\n"
            )
            try:
                async for event in sidecar.chat.run_chat_turn(
                    request.session_id,
                    request.message,
                    provider=provider,
                    model=model,
                    variant=variant,
                    locale=locale,
                ):
                    yield (
                        f"event: {event.type}\ndata: "
                        f"{json.dumps(event.data, default=str)}\n\n"
                    )
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
                # Class and HTTP status only: provider messages can echo credentials.
                logging.getLogger(LOGGER_NAME).warning(
                    "chat_turn_failed provider=%s kind=%s status=%s",
                    provider,
                    type(exc).__name__,
                    getattr(exc, "status", None),
                )
                yield (
                    "event: error\ndata: "
                    f"{json.dumps({'message': 'The agent turn failed unexpectedly. Retry the turn.'})}"
                    "\n\n"
                )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
