"""Self-contained browser-login orchestration for Codex OAuth."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

from .codex_oauth_models import CodexAuthError, CodexCredentials
from .codex_oauth_server import CallbackHandler


class LoginReceipt(TypedDict):
    """Operator-safe successful login result."""

    connected: bool
    auth_mode: str
    account_id_masked: str | None


class CredentialStatus(TypedDict, total=False):
    """Redacted provider status returned to the operator UI."""

    connected: bool
    auth_mode: str | None
    account_id_masked: str | None
    expires_in_seconds: int | None
    relogin_required: bool
    runtime_auth_failed: bool


@dataclass(frozen=True, slots=True)
class LoginBindings:
    """Facade seams captured at call time so monkeypatches remain effective."""

    generate_pkce_pair: Callable[[], tuple[str, str]]
    build_auth_url: Callable[[str], tuple[str, str]]
    open_signin_browser: Callable[[str], bool]
    make_callback_handler: Callable[[str], type[CallbackHandler]]
    wait_for_code: Callable[[type[CallbackHandler], int], str]
    exchange_tokens: Callable[[str, str], Any]
    parse_credentials: Callable[[Any], CodexCredentials | None]
    persist_credentials: Callable[[CodexCredentials], None]
    mask_account_id: Callable[[str | None], str | None]
    logger: logging.Logger


def run_login_flow(
    *,
    open_browser: bool,
    timeout: int,
    bindings: LoginBindings,
) -> LoginReceipt:
    """Run PKCE login and persist app-scoped credentials."""
    code_verifier, code_challenge = bindings.generate_pkce_pair()
    auth_url, state = bindings.build_auth_url(code_challenge)
    bindings.logger.info(
        "codex self-OAuth: starting login flow (open_browser=%s, timeout=%ss)",
        open_browser,
        timeout,
    )
    if open_browser:
        bindings.open_signin_browser(auth_url)
    handler = bindings.make_callback_handler(state)
    auth_code = bindings.wait_for_code(handler, timeout)
    bindings.logger.info(
        "codex self-OAuth: authorization code received — exchanging for tokens"
    )
    try:
        tokens = bindings.exchange_tokens(auth_code, code_verifier)
    except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        bindings.logger.warning(
            "codex self-OAuth token exchange failed: %s", type(exc).__name__
        )
        raise CodexAuthError(
            f"codex 토큰 교환 실패: {type(exc).__name__}"
        ) from None
    creds = bindings.parse_credentials(tokens)
    if creds is None:
        token_shape = sorted(tokens) if isinstance(tokens, Mapping) else type(tokens).__name__
        bindings.logger.warning(
            "codex self-OAuth: token response missing required fields (keys=%s)",
            token_shape,
        )
        raise CodexAuthError("codex 토큰 응답이 올바르지 않습니다.")
    bindings.persist_credentials(creds)
    bindings.logger.info(
        "codex self-OAuth login complete (app-scoped credentials saved)"
    )
    return {
        "connected": True,
        "auth_mode": "app_oauth",
        "account_id_masked": bindings.mask_account_id(creds.account_id),
    }


def credential_status(
    *,
    load_credentials: Callable[[], CodexCredentials | None],
    get_runtime_failure: Callable[[], float | None],
    runtime_failure_superseded: Callable[[CodexCredentials], bool],
    clear_runtime_failure: Callable[[], None],
    mask_account_id: Callable[[str | None], str | None],
    now: Callable[[], float],
) -> CredentialStatus:
    """Build a fail-closed status without exposing credential material."""
    try:
        creds = load_credentials()
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        creds = None
    if creds is None:
        return {
            "connected": False,
            "auth_mode": None,
            "account_id_masked": None,
            "expires_in_seconds": None,
            "relogin_required": True,
        }
    expiry = creds.expires_at
    expires_in = int(expiry - now()) if expiry is not None else None
    runtime_failure_at = get_runtime_failure()
    if runtime_failure_at is not None and runtime_failure_superseded(creds):
        clear_runtime_failure()
    runtime_failure_at = get_runtime_failure()
    if runtime_failure_at is not None:
        return {
            "connected": False,
            "auth_mode": creds.source,
            "account_id_masked": mask_account_id(creds.account_id),
            "expires_in_seconds": expires_in,
            "relogin_required": True,
            "runtime_auth_failed": True,
        }
    return {
        "connected": True,
        "auth_mode": creds.source,
        "account_id_masked": mask_account_id(creds.account_id),
        "expires_in_seconds": expires_in,
        "relogin_required": False,
    }


def build_llm_client(
    *,
    model: str,
    variant: str,
    call_model: Callable[[], Callable[..., str]],
) -> Callable[..., str]:
    """Build the streaming-compatible synchronous preview client."""
    def client(
        *,
        system_prompt: str,
        user_prompt: str,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> str:
        extra: dict[str, Callable[[str], None]] = {}
        if on_delta is not None:
            extra["on_delta"] = on_delta
        if on_reasoning_delta is not None:
            extra["on_reasoning_delta"] = on_reasoning_delta
        return call_model()(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            variant=variant,
            **extra,
        )

    setattr(client, "supports_on_delta", True)
    setattr(client, "supports_on_reasoning_delta", True)
    return client


def build_librarian_client(
    *,
    model: str,
    variant: str,
    tools: list[dict[str, Any]],
    tool_dispatch: Callable[[str, dict[str, Any]], str],
    max_rounds: int,
    on_tool_event: Callable[[str, dict[str, Any]], None] | None,
    call_model_with_tools: Callable[[], Callable[..., str]],
) -> Callable[..., str]:
    """Build the bounded tool-calling librarian client."""
    def client(*, system_prompt: str, user_prompt: str) -> str:
        return call_model_with_tools()(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            variant=variant,
            tools=tools,
            tool_dispatch=tool_dispatch,
            max_rounds=max_rounds,
            on_tool_event=on_tool_event,
        )

    return client


def reauthenticate(
    *,
    verify_model: str | None,
    verify_variant: str,
    get_credentials: Callable[[], CodexCredentials],
    verify_token: Callable[[str, str], bool],
    run_login: Callable[[], LoginReceipt],
    mask_account_id: Callable[[str | None], str | None],
    logger: logging.Logger,
) -> tuple[LoginReceipt, bool]:
    """Try cheap refresh/verification before falling back to browser OAuth."""
    try:
        creds = get_credentials()
    except CodexAuthError as exc:
        logger.info(
            "reauthenticate: refresh path unavailable (%s) — falling back to self-OAuth",
            type(exc).__name__,
        )
        return run_login(), False
    if verify_model and not verify_token(verify_model, verify_variant):
        logger.info(
            "reauthenticate: refreshed token failed live validation (401) — running self-OAuth"
        )
        return run_login(), False
    return (
        {
            "connected": True,
            "auth_mode": creds.source,
            "account_id_masked": mask_account_id(creds.account_id),
        },
        True,
    )


def verify_token(
    model: str,
    variant: str,
    *,
    call_model: Callable[..., str],
) -> bool:
    """Return false only for a genuine authentication rejection."""
    try:
        call_model(
            system_prompt="ping",
            user_prompt="ping",
            model=model,
            variant=variant,
            timeout=20.0,
        )
        return True
    except CodexAuthError as exc:
        return not bool(exc.relogin_required)
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        return True
