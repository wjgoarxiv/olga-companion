"""Authorization-code exchange and single-flight token refresh."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

import httpx

from olga_companion import net

from .codex_oauth_models import CodexAuthError, CodexCredentials


REFRESH_DEAD_ERRORS = (
    "refresh_token_reused",
    "expired",
    "invalidated",
    "invalid_grant",
)

TokenPayload = dict[str, Any]
_INVALID_TOKEN_RESPONSE = "codex 토큰 갱신 응답이 올바르지 않습니다."


def _required_token(payload: TokenPayload, name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise CodexAuthError(_INVALID_TOKEN_RESPONSE)
    return value


def _optional_token(payload: TokenPayload, name: str, fallback: str) -> str:
    value = payload.get(name)
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        raise CodexAuthError(_INVALID_TOKEN_RESPONSE)
    return value


def urlopen_verified(
    request: urllib.request.Request,
    timeout: float = 30.0,
) -> str:
    """Open an OAuth request with certificate verification always enabled."""
    verify: bool | ssl.SSLContext = True
    custom_ca = os.environ.get("CUSTOM_CA_BUNDLE", "").strip()
    if custom_ca and os.path.isfile(custom_ca):
        try:
            verify = ssl.create_default_context(cafile=custom_ca)
        except (OSError, ssl.SSLError, ValueError):
            raise urllib.error.URLError(
                "OAuth TLS 인증서 설정을 확인할 수 없습니다."
            ) from None
    try:
        with net.sync_client(verify=verify, timeout=timeout) as client:
            headers = dict(request.header_items())
            if request.data is not None:
                response = client.post(
                    request.full_url,
                    content=request.data,
                    headers=headers,
                )
            else:
                response = client.get(request.full_url, headers=headers)
            response.raise_for_status()
            return response.text
    except (httpx.HTTPError, OSError, ValueError):
        raise urllib.error.URLError(
            "OAuth 네트워크 연결 또는 TLS 인증서 검증에 실패했습니다."
        ) from None


@dataclass(frozen=True, slots=True)
class RefreshBindings:
    """Facade seams resolved at call time so monkeypatches remain effective."""

    lock: AbstractContextManager[bool]
    load_credentials: Callable[[], CodexCredentials | None]
    post_refresh: Callable[[str], TokenPayload]
    apply_refresh: Callable[[CodexCredentials, TokenPayload], CodexCredentials]
    persist: Callable[[CodexCredentials], None]
    mark_failure: Callable[[], None]
    clear_app_credentials: Callable[[], None]


def post_token_refresh(
    refresh_token: str,
    *,
    client_id: str,
    endpoint: str,
    client_factory: Callable[..., httpx.Client],
    dead_errors: tuple[str, ...] = REFRESH_DEAD_ERRORS,
) -> TokenPayload:
    """POST a refresh grant and map failures to operator-safe errors."""
    body = json.dumps(
        {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    try:
        with client_factory(timeout=30.0, verify=True) as client:
            response = client.post(
                endpoint,
                content=body,
                headers={"Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise CodexAuthError(
            f"codex 토큰 갱신 네트워크 오류: {type(exc).__name__}"
        ) from None

    try:
        data = response.json()
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        data = {}
    if response.status_code >= 400:
        error_code = str(data.get("error", "")).lower() if isinstance(data, dict) else ""
        if any(dead in error_code for dead in dead_errors):
            raise CodexAuthError(
                "codex 로그인이 만료되었습니다. 다시 로그인해 주세요.",
                relogin_required=True,
            )
        raise CodexAuthError(f"codex 토큰 갱신 실패 (HTTP {response.status_code})")
    if not isinstance(data, dict):
        raise CodexAuthError(_INVALID_TOKEN_RESPONSE)
    _required_token(data, "access_token")
    _optional_token(data, "refresh_token", "")
    _optional_token(data, "id_token", "")
    return data


def apply_refresh_response(
    old: CodexCredentials,
    response: TokenPayload,
    *,
    account_id_from_token: Callable[[str], str | None],
) -> CodexCredentials:
    """Build refreshed credentials while carrying over unrotated fields."""
    new_access = _required_token(response, "access_token")
    new_refresh = _optional_token(response, "refresh_token", old.refresh_token)
    new_id = _optional_token(response, "id_token", old.id_token)
    account_id = old.account_id or account_id_from_token(new_id)
    return CodexCredentials(
        access_token=new_access,
        refresh_token=new_refresh,
        id_token=new_id,
        account_id=account_id,
        source=old.source,
    )


def get_fresh_credentials(bindings: RefreshBindings) -> CodexCredentials:
    """Return a usable credential using one locked refresh critical section."""
    creds = bindings.load_credentials()
    if creds is None:
        raise CodexAuthError("codex 로그인이 필요합니다.", relogin_required=True)
    if not creds.is_expiring():
        return creds
    _require_app_refresh_owner(creds)
    with bindings.lock:
        creds = bindings.load_credentials()
        if creds is None:
            raise CodexAuthError("codex 로그인이 필요합니다.", relogin_required=True)
        if not creds.is_expiring():
            return creds
        _require_app_refresh_owner(creds)
        try:
            response = bindings.post_refresh(creds.refresh_token)
        except CodexAuthError as exc:
            if exc.relogin_required:
                bindings.mark_failure()
                if creds.source == "app_oauth":
                    bindings.clear_app_credentials()
            raise
        refreshed = bindings.apply_refresh(creds, response)
        bindings.persist(refreshed)
        return refreshed


def _require_app_refresh_owner(creds: CodexCredentials) -> None:
    if creds.source != "app_oauth":
        raise CodexAuthError(
            "codex CLI 로그인이 만료되었습니다. Codex CLI에서 다시 로그인하거나 "
            "앱 로그인을 사용해 주세요.",
            relogin_required=True,
        )


def exchange_code_for_tokens(
    auth_code: str,
    code_verifier: str,
    *,
    client_id: str,
    endpoint: str,
    redirect_uri: str,
    urlopen_safe: Callable[[urllib.request.Request], str | bytes | bytearray],
) -> TokenPayload:
    """Exchange an authorization code for tokens using PKCE form data."""
    data = {
        "client_id": client_id,
        "code": auth_code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    request = urllib.request.Request(
        endpoint,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return json.loads(urlopen_safe(request))
