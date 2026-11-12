"""Credential-cache and refresh characterization tests for Codex OAuth."""

from __future__ import annotations

import base64
import importlib
import json
import time
from pathlib import Path
from types import TracebackType

import pytest

from olga_companion.llm import codex_oauth


def _jwt(*, exp: float, account_id: str = "account-secret") -> str:
    payload = {
        "exp": exp,
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


def _credentials(*, exp: float, source: str, account_id: str = "account-secret") -> codex_oauth.CodexCredentials:
    return codex_oauth.CodexCredentials(
        access_token=_jwt(exp=exp, account_id=account_id),
        refresh_token=f"refresh-{source}",
        account_id=account_id,
        source=source,
    )


def test_malformed_credential_files_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Given malformed CLI and app-owned credential files.
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("not-json", encoding="utf-8")
    app_tokens = tmp_path / "app" / "codex_tokens.json"
    app_tokens.parent.mkdir()
    app_tokens.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", app_tokens)

    # When both loaders inspect those files.
    cli = codex_oauth._load_codex_cli_credentials()
    app = codex_oauth._load_app_credentials()

    # Then malformed local data is unusable rather than trusted.
    assert cli is None
    assert app is None


def test_app_login_precedes_future_dated_cli_until_app_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a deliberate app login and a later-expiring CLI token.
    now = time.time()
    app = _credentials(exp=now + 3600, source="app_oauth")
    cli = _credentials(exp=now + 7200, source="codex_cli")
    monkeypatch.setattr(codex_oauth, "_load_app_credentials", lambda: app)
    monkeypatch.setattr(codex_oauth, "_load_codex_cli_credentials", lambda: cli)

    # When credential precedence is resolved.
    selected = codex_oauth.load_credentials()

    # Then the intentionally-created live app login wins.
    assert selected is app

    # Given that same app login is now expiring.
    expiring_app = _credentials(exp=now + 1, source="app_oauth")
    monkeypatch.setattr(codex_oauth, "_load_app_credentials", lambda: expiring_app)

    # When precedence is resolved again, the fresher CLI token wins.
    assert codex_oauth.load_credentials() is cli


def test_refresh_rotates_and_persists_once_after_lock_reread(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given an expiring token on both pre-lock and in-lock reads.
    stale = codex_oauth.CodexCredentials(
        access_token="not-a-jwt",
        refresh_token="old-refresh",
        id_token="old-id",
        account_id="account-secret",
        source="app_oauth",
    )
    loads = iter((stale, stale))
    refresh_calls: list[str] = []
    persisted: list[codex_oauth.CodexCredentials] = []
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(codex_oauth, "load_credentials", lambda: next(loads))

    def refresh(token: str) -> dict[str, str]:
        refresh_calls.append(token)
        return {"access_token": "new-access", "refresh_token": "new-refresh"}

    monkeypatch.setattr(codex_oauth, "_post_token_refresh", refresh)
    monkeypatch.setattr(codex_oauth, "_persist_app_credentials", persisted.append)

    # When fresh credentials are requested.
    result = codex_oauth.get_fresh_credentials()

    # Then one refresh rotates and persists the token after the lock reread.
    assert refresh_calls == ["old-refresh"]
    assert result.refresh_token == "new-refresh"
    assert result.id_token == "old-id"
    assert persisted == [result]


def test_atomic_app_cache_is_private_and_never_overwrites_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Given isolated app and CLI-owned files.
    app_tokens = tmp_path / "app" / "codex_tokens.json"
    cli_auth = tmp_path / "codex" / "auth.json"
    cli_auth.parent.mkdir()
    cli_auth.write_text("cli-owned", encoding="utf-8")
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", app_tokens)
    monkeypatch.setenv("CODEX_HOME", str(cli_auth.parent))
    monkeypatch.setattr(codex_oauth, "_clear_runtime_auth_failure", lambda: None)
    creds = _credentials(exp=time.time() + 3600, source="app_oauth")

    # When app credentials are persisted.
    codex_oauth._persist_app_credentials(creds)

    # Then the app cache is private and the CLI-owned source is untouched.
    assert app_tokens.is_file()
    assert app_tokens.stat().st_mode & 0o777 == 0o600
    assert cli_auth.read_text(encoding="utf-8") == "cli-owned"


def test_runtime_failure_status_is_redacted_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given credentials plus a latched server-side auth rejection.
    creds = _credentials(exp=time.time() + 3600, source="app_oauth", account_id="acct-123456")
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(codex_oauth, "_RUNTIME_FAILURE_FILE", tmp_path / "failure.json")
    monkeypatch.setattr(codex_oauth, "load_credentials", lambda: creds)
    monkeypatch.setattr(codex_oauth, "_RUNTIME_AUTH_FAILURE_AT", time.time())
    monkeypatch.setattr(codex_oauth, "_runtime_failure_superseded_by", lambda _creds: False)

    # When operator status is requested.
    status = codex_oauth.credential_status()

    # Then it reports relogin without exposing account or token material.
    assert status == {
        "connected": False,
        "auth_mode": "app_oauth",
        "account_id_masked": "****3456",
        "expires_in_seconds": status["expires_in_seconds"],
        "relogin_required": True,
        "runtime_auth_failed": True,
    }
    serialized = json.dumps(status)
    assert "acct-123456" not in serialized
    assert creds.access_token not in serialized


def test_credential_status_reads_failure_latch_after_credential_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given credential loading that races with a fresh runtime auth failure.
    creds = _credentials(exp=time.time() + 3600, source="app_oauth")
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(codex_oauth, "_RUNTIME_FAILURE_FILE", tmp_path / "failure.json")
    monkeypatch.setattr(codex_oauth, "_RUNTIME_AUTH_FAILURE_AT", None)

    def load_and_mark_failure() -> codex_oauth.CodexCredentials:
        codex_oauth._RUNTIME_AUTH_FAILURE_AT = time.time()
        return creds

    monkeypatch.setattr(codex_oauth, "load_credentials", load_and_mark_failure)
    monkeypatch.setattr(codex_oauth, "_runtime_failure_superseded_by", lambda _creds: False)

    # When status is assembled after the load returns.
    status = codex_oauth.credential_status()

    # Then it fails closed against the live latch instead of a stale snapshot.
    assert status["connected"] is False
    assert status["runtime_auth_failed"] is True

    # And a concurrently cleared latch is not reported from an older snapshot.
    codex_oauth._RUNTIME_AUTH_FAILURE_AT = time.time()

    def load_and_clear_failure() -> codex_oauth.CodexCredentials:
        codex_oauth._RUNTIME_AUTH_FAILURE_AT = None
        return creds

    monkeypatch.setattr(codex_oauth, "load_credentials", load_and_clear_failure)
    assert codex_oauth.credential_status()["connected"] is True


def test_credential_helpers_keep_facade_monkeypatch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given replacements for the helper chain that existed in the monolith.
    monkeypatch.setattr(codex_oauth, "_b64url_decode", lambda _segment: b'{"exp": 123}')
    assert codex_oauth._decode_jwt_payload("one.two.three") == {"exp": 123}

    payload = {
        "exp": 456,
        "https://api.openai.com/auth": {"chatgpt_account_id": "account"},
    }
    monkeypatch.setattr(codex_oauth, "_decode_jwt_payload", lambda _token: payload)
    assert codex_oauth._jwt_expiry("token") == 456.0
    assert codex_oauth._account_id_from_id_token("token") == "account"

    creds = _credentials(exp=time.time() + 3600, source="app_oauth")
    monkeypatch.setattr(codex_oauth, "_jwt_expiry", lambda _token: 789.0)
    monkeypatch.setattr(codex_oauth, "_mask_account_id", lambda _account: "masked")

    # Then the credential value object also resolves the live facade helpers.
    assert creds.expires_at == 789.0
    assert "account_id='masked'" in repr(creds)


def test_deeply_nested_auth_payloads_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given syntactically decodable content deeper than the JSON recursion limit.
    nested_json = b"[" * 10000 + b"0" + b"]" * 10000
    monkeypatch.setattr(codex_oauth, "_b64url_decode", lambda _segment: nested_json)

    # Then JWT helpers return no claims instead of leaking RecursionError.
    assert codex_oauth._decode_jwt_payload("one.two.three") == {}

    app_tokens = tmp_path / "codex_tokens.json"
    app_tokens.write_bytes(nested_json)
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", app_tokens)

    # And local credential loading also fails closed.
    assert codex_oauth._load_app_credentials() is None

    runtime_failure = tmp_path / "failure.json"
    runtime_failure.write_bytes(nested_json)
    monkeypatch.setattr(codex_oauth, "_RUNTIME_FAILURE_FILE", runtime_failure)
    monkeypatch.setattr(codex_oauth, "_RUNTIME_AUTH_FAILURE_AT", None)

    # And persisted runtime-failure state follows the same fail-closed rule.
    codex_oauth._load_persisted_runtime_failure()
    assert codex_oauth._RUNTIME_AUTH_FAILURE_AT is None


def test_facade_reload_rebuilds_mutable_model_tables() -> None:
    # Given a caller mutated a nested compatibility table in memory.
    key = (codex_oauth.DEFAULT_MODEL, codex_oauth.DEFAULT_VARIANT)
    expected = codex_oauth.VARIANTS[key]["reasoning.effort"]
    codex_oauth.VARIANTS[key]["reasoning.effort"] = "reload-sentinel"

    # When only the public facade is reloaded, as callers did with the monolith.
    importlib.reload(codex_oauth)

    # Then the facade reconstructs a pristine compatibility table.
    assert codex_oauth.VARIANTS[key]["reasoning.effort"] == expected


def test_dead_refresh_error_requires_relogin_without_leaking_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a refresh endpoint response that classifies the token as reused.
    class DeadRefreshResponse:
        status_code = 400

        @staticmethod
        def json() -> dict[str, str]:
            return {"error": "refresh_token_reused"}

    class RefreshClient:
        def __init__(self, *, timeout: float, verify: bool) -> None:
            self.timeout = timeout
            assert verify is True

        def __enter__(self) -> RefreshClient:
            return self

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: TracebackType | None,
        ) -> None:
            return None

        def post(
            self,
            _endpoint: str,
            *,
            content: bytes,
            headers: dict[str, str],
        ) -> DeadRefreshResponse:
            del content, headers
            return DeadRefreshResponse()

    monkeypatch.setattr(codex_oauth.httpx, "Client", RefreshClient)

    # When the refresh grant is posted with a sensitive token.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth._post_token_refresh("secret-refresh-token")

    # Then the typed relogin signal is set and no secret reaches the message.
    assert captured.value.relogin_required is True
    assert str(captured.value) == "codex 로그인이 만료되었습니다. 다시 로그인해 주세요."
    assert "secret-refresh-token" not in str(captured.value)
