"""High-level API orchestration behind the ``codex_oauth`` facade."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

import httpx  # noqa: F401 — kept so test monkeypatches of httpx still bind here

from olga_companion import net

from . import (
    codex_oauth_cache as cache,
    codex_oauth_login as login_flow,
    codex_oauth_responses as responses,
    codex_oauth_server as callback_server,
    codex_oauth_tools as tools_transport,
)
from .codex_oauth_models import DEFAULT_MODEL, DEFAULT_VARIANT, CodexCredentials
from .codex_oauth_server import CallbackHandler, CallbackServer
from .codex_oauth_tools import DEFAULT_MAX_TOOL_ROUNDS


class OAuthFacade(Protocol):
    """Dynamic facade surface used to preserve module-level monkeypatch seams."""

    REDIRECT_PORT: int
    RESPONSES_ENDPOINT: str
    APP_TOKENS_FILE: Path
    CodexAuthError: type[Exception]
    _RUNTIME_AUTH_FAILURE_AT: float | None
    _refresh_guard: Callable[[], AbstractContextManager[bool]]
    _load_persisted_runtime_failure: Callable[[], None]
    logger: logging.Logger
    HTTPServer: Callable[[tuple[str, int], type[CallbackHandler]], CallbackServer]
    generate_pkce_pair: Callable[[], tuple[str, str]]
    make_oauth_callback_handler: Callable[[str], type[CallbackHandler]]
    build_codex_auth_url: Callable[[str], tuple[str, str]]
    _open_signin_browser: Callable[[str], bool]
    _exchange_code_for_tokens: Callable[[str, str], dict[str, Any]]
    _credentials_from_tokens: Callable[..., CodexCredentials | None]
    _persist_app_credentials: Callable[[CodexCredentials], None]
    _mask_account_id: Callable[[str | None], str | None]
    resolve_variant: Callable[[str, str], dict[str, str]]
    get_fresh_credentials: Callable[[], CodexCredentials]
    _mark_runtime_auth_failure: Callable[[], None]
    _extract_text_from_event: Callable[[dict[str, Any]], str]
    _accumulate_tool_call_events: Callable[
        [dict[str, Any], dict[str, dict[str, Any]]], None
    ]
    _stream_codex_round: Callable[..., tuple[str, list[dict[str, Any]]]]
    TOOL_RESULT_MAX_CHARS: int
    load_credentials: Callable[[], CodexCredentials | None]
    _runtime_failure_superseded_by: Callable[[CodexCredentials], bool]
    _clear_runtime_auth_failure: Callable[[], None]
    call_codex_model: Callable[..., str]
    call_codex_model_with_tools: Callable[..., str]
    _verify_codex_token: Callable[[str, str], bool]
    run_self_oauth_login: Callable[..., dict[str, Any]]


def _facade() -> OAuthFacade:
    from . import codex_oauth

    return codex_oauth


def run_self_oauth_login(
    *, open_browser: bool = True, timeout: int = 300
) -> dict[str, Any]:
    facade = _facade()
    bindings = login_flow.LoginBindings(
        generate_pkce_pair=facade.generate_pkce_pair,
        build_auth_url=facade.build_codex_auth_url,
        open_signin_browser=facade._open_signin_browser,
        make_callback_handler=facade.make_oauth_callback_handler,
        wait_for_code=lambda handler, budget: callback_server.wait_for_authorization_code(
            handler,
            port=facade.REDIRECT_PORT,
            timeout=budget,
            server_factory=facade.HTTPServer,
            monotonic=time.monotonic,
            logger=facade.logger,
        ),
        exchange_tokens=facade._exchange_code_for_tokens,
        parse_credentials=lambda data: facade._credentials_from_tokens(
            data, source="app_oauth"
        ),
        persist_credentials=facade._persist_app_credentials,
        mask_account_id=facade._mask_account_id,
        logger=facade.logger,
    )
    return login_flow.run_login_flow(
        open_browser=open_browser, timeout=timeout, bindings=bindings
    )


def call_codex_model(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    variant: str,
    on_delta: Callable[[str], None] | None = None,
    on_reasoning_delta: Callable[[str], None] | None = None,
    timeout: float = 120.0,
) -> str:
    from .llm_policy import apply_global_llm_policy

    facade = _facade()
    config = facade.resolve_variant(model, variant)
    system_prompt = apply_global_llm_policy(system_prompt)
    creds = facade.get_fresh_credentials()
    return responses.call_model(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        config=config,
        creds=creds,
        bindings=responses.ResponseBindings(
            endpoint=facade.RESPONSES_ENDPOINT,
            client_factory=net.sync_client,
            mark_auth_failure=facade._mark_runtime_auth_failure,
            extract_text=facade._extract_text_from_event,
        ),
        on_delta=on_delta,
        on_reasoning_delta=on_reasoning_delta,
        timeout=timeout,
    )


def stream_codex_round(
    *,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float = 300.0,
) -> tuple[str, list[dict[str, Any]]]:
    facade = _facade()
    return tools_transport.stream_codex_round(
        body=body,
        headers=headers,
        timeout=timeout,
        bindings=tools_transport.ToolRoundBindings(
            endpoint=facade.RESPONSES_ENDPOINT,
            client_factory=net.sync_client,
            mark_auth_failure=facade._mark_runtime_auth_failure,
            extract_text=facade._extract_text_from_event,
            accumulate_tool_calls=facade._accumulate_tool_call_events,
        ),
    )


def call_codex_model_with_tools(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    variant: str,
    tools: list[dict[str, Any]],
    tool_dispatch: Callable[[str, dict[str, Any]], str],
    max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    on_tool_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    from .llm_policy import apply_global_llm_policy

    facade = _facade()
    config = facade.resolve_variant(model, variant)
    system_prompt = apply_global_llm_policy(system_prompt)
    creds = facade.get_fresh_credentials()
    return tools_transport.call_model_with_tools(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        config=config,
        creds=creds,
        tools=tools,
        tool_dispatch=tool_dispatch,
        max_rounds=max_rounds,
        tool_result_max_chars=facade.TOOL_RESULT_MAX_CHARS,
        on_tool_event=on_tool_event,
        stream_round=facade._stream_codex_round,
    )


def credential_status() -> dict[str, Any]:
    facade = _facade()
    with facade._refresh_guard():
        facade._load_persisted_runtime_failure()
        return dict(
            login_flow.credential_status(
                load_credentials=facade.load_credentials,
                get_runtime_failure=lambda: facade._RUNTIME_AUTH_FAILURE_AT,
                runtime_failure_superseded=facade._runtime_failure_superseded_by,
                clear_runtime_failure=facade._clear_runtime_auth_failure,
                mask_account_id=facade._mask_account_id,
                now=time.time,
            )
        )


def build_codex_llm_client(
    *, model: str = DEFAULT_MODEL, variant: str = DEFAULT_VARIANT
) -> Callable[..., str]:
    facade = _facade()
    facade.resolve_variant(model, variant)
    return login_flow.build_llm_client(
        model=model, variant=variant, call_model=lambda: _facade().call_codex_model
    )


def build_codex_librarian_client(
    *,
    model: str = DEFAULT_MODEL,
    variant: str = DEFAULT_VARIANT,
    tools: list[dict[str, Any]],
    tool_dispatch: Callable[[str, dict[str, Any]], str],
    max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    on_tool_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> Callable[..., str]:
    facade = _facade()
    facade.resolve_variant(model, variant)
    return login_flow.build_librarian_client(
        model=model,
        variant=variant,
        tools=tools,
        tool_dispatch=tool_dispatch,
        max_rounds=max_rounds,
        on_tool_event=on_tool_event,
        call_model_with_tools=lambda: _facade().call_codex_model_with_tools,
    )


def login() -> dict[str, Any]:
    return _facade().run_self_oauth_login()


def logout() -> None:
    facade = _facade()
    with facade._refresh_guard():
        deleted = cache.delete_app_tokens(
            facade.APP_TOKENS_FILE,
            logger=facade.logger,
            label="codex logout: could not delete token file",
        )
        if deleted:
            facade._clear_runtime_auth_failure()
        else:
            facade._mark_runtime_auth_failure()
            raise facade.CodexAuthError(
                "codex 로그아웃에 실패했습니다. 토큰 파일 권한을 확인해 주세요."
            )


def reauthenticate(
    *, verify_model: str | None = None, verify_variant: str = "low"
) -> dict[str, Any]:
    facade = _facade()
    receipt, refreshed = login_flow.reauthenticate(
        verify_model=verify_model,
        verify_variant=verify_variant,
        get_credentials=facade.get_fresh_credentials,
        verify_token=facade._verify_codex_token,
        run_login=facade.run_self_oauth_login,
        mask_account_id=facade._mask_account_id,
        logger=facade.logger,
    )
    if refreshed:
        facade._clear_runtime_auth_failure()
    return receipt


def verify_codex_token(model: str, variant: str = "low") -> bool:
    return login_flow.verify_token(
        model, variant, call_model=_facade().call_codex_model
    )
