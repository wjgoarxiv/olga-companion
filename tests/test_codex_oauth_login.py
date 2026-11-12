"""PKCE callback and browser-login characterization tests for Codex OAuth."""

from __future__ import annotations

import io
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from types import TracebackType
from typing import Any

import httpx
import pytest

from olga_companion.llm import codex_oauth


class _Handler:
    authorization_code: str | None = None


class ExchangeFailureError(Exception):
    """Typed test failure returned by the mocked token exchange."""


class _Server:
    instance: _Server | None = None

    def __init__(self, address: tuple[str, int], handler: type[_Handler]) -> None:
        self.address = address
        self.handler = handler
        self.timeout: int | None = None
        self.requests = 0
        self.closed = False
        type(self).instance = self

    def handle_request(self) -> None:
        self.requests += 1
        if self.requests == 2:
            self.handler.authorization_code = "authorization-code"

    def server_close(self) -> None:
        self.closed = True


def _invoke_callback(path: str) -> tuple[type[Any], list[int], bytes]:
    handler_type = codex_oauth.make_oauth_callback_handler("expected-state")
    handler = handler_type.__new__(handler_type)
    handler.path = path
    handler.wfile = io.BytesIO()
    statuses: list[int] = []
    handler.send_response = statuses.append
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler.do_GET()
    return handler_type, statuses, handler.wfile.getvalue()


def _patch_successful_callback(monkeypatch: pytest.MonkeyPatch) -> list[codex_oauth.CodexCredentials]:
    _Handler.authorization_code = None
    _Server.instance = None
    persisted: list[codex_oauth.CodexCredentials] = []
    monkeypatch.setattr(codex_oauth, "generate_pkce_pair", lambda: ("verifier", "challenge"))
    monkeypatch.setattr(codex_oauth, "build_codex_auth_url", lambda _challenge: ("https://signin", "state"))
    monkeypatch.setattr(codex_oauth, "_open_signin_browser", lambda _url: True)
    monkeypatch.setattr(codex_oauth, "make_oauth_callback_handler", lambda _state: _Handler)
    monkeypatch.setattr(codex_oauth, "HTTPServer", _Server)
    monkeypatch.setattr(
        codex_oauth,
        "_exchange_code_for_tokens",
        lambda code, verifier: {
            "access_token": f"access-{code}",
            "refresh_token": f"refresh-{verifier}",
            "account_id": "account-123456",
        },
    )
    monkeypatch.setattr(codex_oauth, "_persist_app_credentials", persisted.append)
    return persisted


def test_auth_url_binds_pkce_state_and_registered_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given deterministic CSRF state generation.
    monkeypatch.setattr(secrets, "token_urlsafe", lambda _size: "csrf-state")

    # When the authorization URL is built.
    url, state = codex_oauth.build_codex_auth_url("pkce-challenge")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    # Then the state, PKCE challenge, redirect, and offline scope are bound together.
    assert state == "csrf-state"
    assert query["state"] == [state]
    assert query["code_challenge"] == ["pkce-challenge"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [codex_oauth.REDIRECT_URI]
    assert query["scope"] == [codex_oauth.OAUTH_SCOPES]


def test_self_login_ignores_stray_request_and_returns_only_safe_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a callback server whose first request is stray and second carries the code.
    persisted = _patch_successful_callback(monkeypatch)

    # When the self-contained browser login runs.
    result = codex_oauth.run_self_oauth_login(timeout=20)

    # Then it waits for the valid callback, closes the server, and returns no secrets.
    server = _Server.instance
    assert server is not None
    assert server.address == ("localhost", codex_oauth.REDIRECT_PORT)
    assert server.requests == 2
    assert server.closed is True
    assert len(persisted) == 1
    assert result == {
        "connected": True,
        "auth_mode": "app_oauth",
        "account_id_masked": "****3456",
    }
    assert "access" not in repr(result)
    assert "refresh" not in repr(result)


def test_self_login_preserves_callback_bind_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a callback server factory that cannot bind the registered port.
    monkeypatch.setattr(codex_oauth, "generate_pkce_pair", lambda: ("verifier", "challenge"))
    monkeypatch.setattr(codex_oauth, "build_codex_auth_url", lambda _challenge: ("https://signin", "state"))
    monkeypatch.setattr(codex_oauth, "make_oauth_callback_handler", lambda _state: _Handler)

    class BindFailure:
        def __init__(
            self, _address: tuple[str, int], _handler: type[_Handler]
        ) -> None:
            raise OSError("address in use")

    monkeypatch.setattr(codex_oauth, "HTTPServer", BindFailure)

    # When login tries to host the callback.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth.run_self_oauth_login(open_browser=False)

    # Then the exact operator-safe bind error is preserved.
    assert str(captured.value) == "콜백 포트 1455 사용 불가: OSError"


def test_self_login_redacts_token_exchange_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a valid callback followed by an exchange exception containing a secret.
    _patch_successful_callback(monkeypatch)

    def fail_exchange(_code: str, _verifier: str) -> dict[str, str]:
        raise ExchangeFailureError("server echoed secret-token")

    monkeypatch.setattr(codex_oauth, "_exchange_code_for_tokens", fail_exchange)

    # When the exchange fails.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth.run_self_oauth_login(open_browser=False)

    # Then only the failure type is surfaced.
    assert str(captured.value) == "codex 토큰 교환 실패: ExchangeFailureError"
    assert "secret-token" not in str(captured.value)


def test_self_login_maps_non_object_token_response_to_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a completed callback whose token endpoint returns a JSON array.
    _patch_successful_callback(monkeypatch)
    monkeypatch.setattr(codex_oauth, "_exchange_code_for_tokens", lambda *_args: [])

    # When login validates the malformed response.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth.run_self_oauth_login(open_browser=False)

    # Then it fails closed with the established safe operator message.
    assert str(captured.value) == "codex 토큰 응답이 올바르지 않습니다."


def test_callback_rejects_mismatched_state_without_accepting_code() -> None:
    # Given a per-flow callback handler and an attacker-controlled state/code.
    handler_type, statuses, body = _invoke_callback(
        "/auth/callback?code=stolen-code&state=wrong-state"
    )

    # Then CSRF validation rejects it and no authorization code is retained.
    assert statuses == [400]
    assert handler_type.authorization_code is None
    assert b"invalid_state" in body


@pytest.mark.parametrize(
    "path",
    (
        "/wrong?code=code&state=expected-state",
        "/auth/callback?code=code",
        "/auth/callback?code=code&state=expected-state&state=expected-state",
        "/auth/callback?code=one&code=two&state=expected-state",
    ),
)
def test_callback_rejects_wrong_path_missing_or_duplicate_parameters(path: str) -> None:
    # When a callback is ambiguous or does not target the registered path.
    handler_type, statuses, body = _invoke_callback(path)

    # Then it is rejected before the authorization code can be retained.
    assert statuses == [400]
    assert handler_type.authorization_code is None
    assert body == b"invalid OAuth callback"


def test_code_exchange_uses_exact_pkce_form_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a capture seam for the verified token transport.
    captured: list[urllib.request.Request] = []

    def capture(request: urllib.request.Request) -> str:
        captured.append(request)
        return '{"access_token":"access","refresh_token":"refresh"}'

    monkeypatch.setattr(codex_oauth, "_urlopen_safe", capture)

    # When an authorization code is exchanged.
    result = codex_oauth._exchange_code_for_tokens("authorization-code", "pkce-verifier")

    # Then the registered redirect and verifier are form encoded exactly once.
    request = captured[0]
    assert request.full_url == codex_oauth.TOKEN_ENDPOINT
    assert request.headers["Content-type"] == "application/x-www-form-urlencoded"
    assert urllib.parse.parse_qs(request.data.decode(), strict_parsing=True) == {
        "client_id": [codex_oauth.CLIENT_ID],
        "code": ["authorization-code"],
        "code_verifier": ["pkce-verifier"],
        "grant_type": ["authorization_code"],
        "redirect_uri": [codex_oauth.REDIRECT_URI],
    }
    assert result["access_token"] == "access"


def test_token_exchange_transport_never_retries_with_tls_verification_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given every verified network path fails and a request contains OAuth secrets.
    verify_values: list[Any] = []

    class FailingOpener:
        def open(self, *_args: Any, **_kwargs: Any) -> None:
            raise urllib.error.URLError("offline")

    class FailingClient:
        def __init__(self, *, verify: Any, timeout: float) -> None:
            verify_values.append(verify)

        def __enter__(self) -> FailingClient:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            del exc_type, exc, traceback
            return None

        def post(self, *_args: Any, **_kwargs: Any) -> None:
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: FailingOpener())
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    monkeypatch.setattr(codex_oauth.httpx, "Client", FailingClient)
    request = urllib.request.Request(
        codex_oauth.TOKEN_ENDPOINT,
        data=b"code=secret-code&code_verifier=secret-verifier",
    )

    # When the verified exchange transport is exhausted.
    with pytest.raises(urllib.error.URLError) as captured:
        codex_oauth._urlopen_safe(request)

    # Then no attempt disables TLS verification and no secret reaches the error.
    assert verify_values
    assert False not in verify_values
    assert "secret" not in str(captured.value)


def test_browser_fallback_uses_windows_shell_open(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a browser module that reports no launch and an available shell-open seam.
    opened: list[str] = []
    monkeypatch.setattr(codex_oauth.webbrowser, "open", lambda _url: False)
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)

    # When automatic sign-in opening runs.
    result = codex_oauth._open_signin_browser("https://signin")

    # Then the Windows shell fallback is used.
    assert result is True
    assert opened == ["https://signin"]
