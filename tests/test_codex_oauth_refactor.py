"""Compatibility and architecture locks for the Codex OAuth module family."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from olga_companion.llm import codex_oauth


class _StreamResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __enter__(self) -> _StreamResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        return None

    def iter_lines(self) -> Iterator[str]:
        return iter(self._lines)


class _StreamClient:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __enter__(self) -> _StreamClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        return None

    def stream(self, *_args: Any, **_kwargs: Any) -> _StreamResponse:
        return _StreamResponse(self._lines)


EXPECTED_MODULES = {
    "codex_oauth.py",
    "codex_oauth_cache.py",
    "codex_oauth_callback.py",
    "codex_oauth_lock.py",
    "codex_oauth_login.py",
    "codex_oauth_models.py",
    "codex_oauth_responses.py",
    "codex_oauth_runtime.py",
    "codex_oauth_server.py",
    "codex_oauth_tokens.py",
    "codex_oauth_tools.py",
}

COMPATIBILITY_NAMES = {
    "APP_TOKENS_FILE",
    "AUTH_ENDPOINT",
    "CLIENT_ID",
    "DEFAULT_MAX_TOOL_ROUNDS",
    "DEFAULT_MODEL",
    "DEFAULT_VARIANT",
    "MODEL_DEFAULT_VARIANTS",
    "MODEL_VARIANTS",
    "OAUTH_SCOPES",
    "REDIRECT_PORT",
    "REDIRECT_URI",
    "REFRESH_WINDOW_SECONDS",
    "RESPONSES_ENDPOINT",
    "SUPPORTED_MODELS",
    "SUPPORTED_VARIANTS",
    "TOKEN_ENDPOINT",
    "TOOL_RESULT_MAX_CHARS",
    "VARIANTS",
    "CodexAuthError",
    "CodexCredentials",
    "_account_id_from_id_token",
    "_accumulate_tool_call_events",
    "_apply_refresh_response",
    "_atomic_write_app_tokens",
    "_b64url_decode",
    "_clear_app_credentials",
    "_clear_runtime_auth_failure",
    "_codex_home",
    "_collect_output_text",
    "_credential_source_path",
    "_credentials_from_tokens",
    "_decode_jwt_payload",
    "_exchange_code_for_tokens",
    "_expiry_sort_key",
    "_extract_text_from_event",
    "_jwt_expiry",
    "_load_app_credentials",
    "_load_codex_cli_credentials",
    "_load_persisted_runtime_failure",
    "_mark_runtime_auth_failure",
    "_mask_account_id",
    "_open_signin_browser",
    "_persist_app_credentials",
    "_post_token_refresh",
    "_REFRESH_LOCK",
    "_RUNTIME_AUTH_FAILURE_AT",
    "_RUNTIME_FAILURE_FILE",
    "_runtime_failure_superseded_by",
    "_stream_codex_round",
    "_urlopen_safe",
    "_VARIANT_PROFILE",
    "_verify_codex_token",
    "HTTPServer",
    "build_codex_auth_url",
    "build_codex_librarian_client",
    "build_codex_llm_client",
    "call_codex_model",
    "call_codex_model_with_tools",
    "codex_auth_json_path",
    "credential_status",
    "default_variant",
    "get_fresh_credentials",
    "load_credentials",
    "login",
    "logout",
    "generate_pkce_pair",
    "httpx",
    "make_oauth_callback_handler",
    "reauthenticate",
    "resolve_variant",
    "run_self_oauth_login",
    "supported_variants",
}


def _pure_loc(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def test_codex_oauth_module_family_stays_below_250_pure_lines() -> None:
    # Given the source module family that owns Codex OAuth.
    module_dir = Path(codex_oauth.__file__).parent
    paths = {path.name: path for path in module_dir.glob("codex_oauth*.py")}

    # When the architectural ceiling and expected boundaries are inspected.
    missing = EXPECTED_MODULES - paths.keys()
    oversized = {name: _pure_loc(path) for name, path in paths.items() if _pure_loc(path) >= 250}

    # Then every boundary exists and every source module remains below the ceiling.
    assert not missing
    assert not oversized


def test_codex_oauth_facade_preserves_import_surface() -> None:
    # Given compatibility names imported by callers and tests before the split.
    # When the facade is inspected after module extraction.
    missing = {name for name in COMPATIBILITY_NAMES if not hasattr(codex_oauth, name)}

    # Then no import path was removed.
    assert not missing


def test_get_fresh_credentials_keeps_facade_monkeypatch_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given an expiring credential and facade-level refresh/persist patches.
    stale = codex_oauth.CodexCredentials(
        access_token="not-a-jwt",
        refresh_token="old-refresh",
        account_id="account",
        source="app_oauth",
    )
    loads = iter((stale, stale))
    applied: list[tuple[codex_oauth.CodexCredentials, dict[str, str]]] = []
    persisted: list[codex_oauth.CodexCredentials] = []
    monkeypatch.setattr(codex_oauth, "_refresh_guard", lambda: codex_oauth._REFRESH_LOCK)
    monkeypatch.setattr(codex_oauth, "load_credentials", lambda: next(loads))
    monkeypatch.setattr(
        codex_oauth,
        "_post_token_refresh",
        lambda _token: {"access_token": "new-access", "refresh_token": "new-refresh"},
    )

    def apply_refresh(
        old: codex_oauth.CodexCredentials,
        response: dict[str, str],
    ) -> codex_oauth.CodexCredentials:
        applied.append((old, response))
        return codex_oauth.CodexCredentials(
            access_token=response["access_token"],
            refresh_token=response["refresh_token"],
            account_id=old.account_id,
            source=old.source,
        )

    monkeypatch.setattr(codex_oauth, "_apply_refresh_response", apply_refresh)
    monkeypatch.setattr(codex_oauth, "_persist_app_credentials", persisted.append)

    # When the facade refresh orchestration runs.
    refreshed = codex_oauth.get_fresh_credentials()

    # Then patched seams are honored and the rotated credential is persisted.
    assert refreshed.access_token == "new-access"
    assert refreshed.refresh_token == "new-refresh"
    assert applied == [(stale, {"access_token": "new-access", "refresh_token": "new-refresh"})]
    assert persisted == [refreshed]


def test_reauthenticate_keeps_facade_login_fallback_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a facade-level refresh failure and a patched browser-login fallback.
    def raise_refresh_failure() -> codex_oauth.CodexCredentials:
        raise codex_oauth.CodexAuthError("refresh unavailable", relogin_required=True)

    expected = {"connected": True, "auth_mode": "app_oauth"}
    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", raise_refresh_failure)
    monkeypatch.setattr(codex_oauth, "run_self_oauth_login", lambda: expected)

    # When reauthentication runs.
    result = codex_oauth.reauthenticate()

    # Then it calls the patched facade fallback and preserves its safe result.
    assert result is expected


def test_response_and_tool_parsers_keep_facade_monkeypatch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given parser replacements on the compatibility facade.
    creds = codex_oauth.CodexCredentials(
        access_token="access",
        refresh_token="refresh",
        account_id="account",
        source="app_oauth",
    )
    lines = ['data: {"type":"custom"}', "data: [DONE]"]
    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", lambda: creds)
    monkeypatch.setattr(codex_oauth.httpx, "Client", lambda **_kwargs: _StreamClient(lines))
    monkeypatch.setattr(codex_oauth, "_collect_output_text", lambda _output: "collected")
    assert codex_oauth._extract_text_from_event(
        {"type": "response.completed", "response": {"output": []}}
    ) == "collected"
    monkeypatch.setattr(codex_oauth, "_extract_text_from_event", lambda _event: "patched")

    # When both response transports parse an event.
    output = codex_oauth.call_codex_model(
        system_prompt="system",
        user_prompt="user",
        model=codex_oauth.DEFAULT_MODEL,
        variant=codex_oauth.DEFAULT_VARIANT,
    )
    monkeypatch.setattr(
        codex_oauth,
        "_accumulate_tool_call_events",
        lambda _event, pending: pending.update(
            {"item": {"call_id": "call", "name": "tool", "arguments": "{}"}}
        ),
    )
    _text, calls = codex_oauth._stream_codex_round(body={}, headers={})

    # Then the extracted boundaries honor the facade replacements.
    assert output == "patched"
    assert calls == [
        {"call_id": "call", "name": "tool", "arguments": "{}", "item_id": "item"}
    ]


def test_tool_result_limit_keeps_facade_monkeypatch_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a small facade-level result cap and a two-round tool exchange.
    creds = codex_oauth.CodexCredentials(
        access_token="access",
        refresh_token="refresh",
        account_id="account",
        source="app_oauth",
    )
    bodies: list[dict[str, Any]] = []

    def stream_round(*, body: dict[str, Any], headers: dict[str, str]) -> tuple[str, list[dict[str, str]]]:
        del headers
        bodies.append(body)
        if len(bodies) == 1:
            return "", [{"call_id": "call", "name": "tool", "arguments": "{}", "item_id": "item"}]
        return "done", []

    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", lambda: creds)
    monkeypatch.setattr(codex_oauth, "_stream_codex_round", stream_round)
    monkeypatch.setattr(codex_oauth, "TOOL_RESULT_MAX_CHARS", 4)

    # When a long tool result is folded into the next request.
    output = codex_oauth.call_codex_model_with_tools(
        system_prompt="system",
        user_prompt="user",
        model=codex_oauth.DEFAULT_MODEL,
        variant=codex_oauth.DEFAULT_VARIANT,
        tools=[],
        tool_dispatch=lambda _name, _args: "abcdefgh",
    )

    # Then the live facade cap is used rather than a copied module constant.
    assert output == "done"
    assert bodies[1]["input"][-1]["output"] == "abcd …(truncated)"
