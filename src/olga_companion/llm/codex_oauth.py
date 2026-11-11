"""Compatibility facade for the modular Codex (ChatGPT) OAuth client.

Tokens remain secret, the Codex CLI credential file remains read-only, and app
credentials are atomically persisted with platform privacy hardening. Credential
mutations share one reentrant local and interprocess guard. Existing imports and
monkeypatch seams stay rooted here while cohesive behavior lives in sibling modules.
"""
from __future__ import annotations

import base64 as base64
import json as json
import logging
import os
import secrets
import tempfile as tempfile
import threading
import time
import uuid as uuid
import webbrowser
from contextlib import AbstractContextManager
from http.server import HTTPServer as HTTPServer
from pathlib import Path
from typing import Any, Callable as Callable, Optional

import httpx

from . import (
    codex_oauth_cache as _cache,
    codex_oauth_callback as _callback,
    codex_oauth_lock as _lock,
    codex_oauth_models as _models,
    codex_oauth_responses as _responses,
    codex_oauth_runtime as _runtime,
    codex_oauth_tokens as _tokens,
    codex_oauth_tools as _tools,
)
from .openai_auth import (
    generate_pkce_pair as generate_pkce_pair,
    make_oauth_callback_handler as _legacy_callback_handler,
)

logger = logging.getLogger(__name__)

CLIENT_ID = _models.CLIENT_ID
AUTH_ENDPOINT = _models.AUTH_ENDPOINT
TOKEN_ENDPOINT = _models.TOKEN_ENDPOINT
REDIRECT_PORT = _models.REDIRECT_PORT
REDIRECT_URI = _models.REDIRECT_URI
OAUTH_SCOPES = _models.OAUTH_SCOPES
RESPONSES_ENDPOINT = _models.RESPONSES_ENDPOINT
REFRESH_WINDOW_SECONDS = _models.REFRESH_WINDOW_SECONDS
MODEL_VARIANTS = {model: tuple(variants) for model, variants in _models.MODEL_VARIANTS.items()}
SUPPORTED_MODELS = _models.SUPPORTED_MODELS
SUPPORTED_VARIANTS = _models.SUPPORTED_VARIANTS
_VARIANT_PROFILE = {name: dict(profile) for name, profile in _models._VARIANT_PROFILE.items()}
VARIANTS = {key: dict(config) for key, config in _models.VARIANTS.items()}
DEFAULT_MODEL = _models.DEFAULT_MODEL
DEFAULT_VARIANT = _models.DEFAULT_VARIANT
MODEL_DEFAULT_VARIANTS = dict(_models.MODEL_DEFAULT_VARIANTS)
TOOL_RESULT_MAX_CHARS = _tools.TOOL_RESULT_MAX_CHARS
DEFAULT_MAX_TOOL_ROUNDS = _tools.DEFAULT_MAX_TOOL_ROUNDS
_REFRESH_DEAD_ERRORS = _tokens.REFRESH_DEAD_ERRORS
_urlopen_safe = _tokens.urlopen_verified

CodexAuthError = _models.CodexAuthError
CodexCredentials = _models.CodexCredentials
_b64url_decode = _models.b64url_decode
_mask_account_id = _models.mask_account_id
_collect_output_text = _responses.collect_output_text
_accumulate_tool_call_events = _tools.accumulate_tool_call_events
_expiry_sort_key = _cache.expiry_sort_key


def _extract_text_from_event(payload: dict[str, Any]) -> str:
    return _responses.extract_text_from_event(
        payload, collect_output=_collect_output_text
    )


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    return _models.decode_jwt_payload(token, decode_segment=_b64url_decode)


def _jwt_expiry(token: str) -> float | None:
    return _models.jwt_expiry(token, decode_payload=_decode_jwt_payload)


def _account_id_from_id_token(id_token: str) -> str | None:
    return _models.account_id_from_id_token(
        id_token, decode_payload=_decode_jwt_payload
    )

APP_TOKENS_FILE = Path.home() / ".olga_copilot" / "codex_tokens.json"
_RUNTIME_FAILURE_FILE = Path.home() / ".olga_copilot" / "codex_auth_failure.json"
_REFRESH_LOCK = threading.Lock()
_REFRESH_GUARD_STATE = _lock.RefreshGuardState()
_RUNTIME_AUTH_FAILURE_AT: float | None = None


def supported_variants(model: str) -> tuple[str, ...]:
    return MODEL_VARIANTS.get(model, ())


def default_variant(model: str) -> str:
    return MODEL_DEFAULT_VARIANTS.get(model, DEFAULT_VARIANT)


def resolve_variant(model: str, variant: str) -> dict[str, str]:
    key = (model, variant)
    if key not in VARIANTS:
        raise CodexAuthError(f"지원하지 않는 모델/변형입니다: model={model!r} variant={variant!r}")
    return dict(VARIANTS[key])


def _mark_runtime_auth_failure() -> None:
    global _RUNTIME_AUTH_FAILURE_AT
    with _refresh_guard():
        _RUNTIME_AUTH_FAILURE_AT = time.time()
        _cache.write_runtime_failure(_RUNTIME_FAILURE_FILE, _RUNTIME_AUTH_FAILURE_AT)


def _clear_runtime_auth_failure() -> None:
    global _RUNTIME_AUTH_FAILURE_AT
    with _refresh_guard():
        if _cache.delete_runtime_failure(_RUNTIME_FAILURE_FILE):
            _RUNTIME_AUTH_FAILURE_AT = None


def _load_persisted_runtime_failure() -> None:
    global _RUNTIME_AUTH_FAILURE_AT
    persisted = _cache.load_runtime_failure(_RUNTIME_FAILURE_FILE)
    if persisted is not None and (
        _RUNTIME_AUTH_FAILURE_AT is None or persisted > _RUNTIME_AUTH_FAILURE_AT
    ):
        _RUNTIME_AUTH_FAILURE_AT = persisted


def _codex_home() -> Path:
    env_home = os.environ.get("CODEX_HOME", "").strip()
    return Path(env_home) if env_home else Path.home() / ".codex"


def codex_auth_json_path() -> Path:
    return _codex_home() / "auth.json"


def _credentials_from_tokens(tokens: dict[str, Any], *, source: str) -> Optional[CodexCredentials]:
    if not isinstance(tokens, dict):
        return None
    return _cache.credentials_from_tokens(
        tokens, source=source, account_id_from_token=_account_id_from_id_token
    )


def _load_codex_cli_credentials() -> Optional[CodexCredentials]:
    return _cache.load_credentials_file(
        codex_auth_json_path(),
        warning_label="codex auth.json",
        logger=logger,
        parser=lambda tokens: _credentials_from_tokens(tokens, source="codex_cli"),
    )


def _load_app_credentials() -> Optional[CodexCredentials]:
    return _cache.load_credentials_file(
        APP_TOKENS_FILE,
        warning_label="app codex tokens",
        logger=logger,
        parser=lambda tokens: _credentials_from_tokens(tokens, source="app_oauth"),
        private_owned=True,
    )


def load_credentials() -> Optional[CodexCredentials]:
    cli_creds, app_creds = _load_codex_cli_credentials(), _load_app_credentials()
    if cli_creds is None:
        return app_creds
    if app_creds is None or not app_creds.is_expiring():
        return cli_creds if app_creds is None else app_creds
    return app_creds if _expiry_sort_key(app_creds) > _expiry_sort_key(cli_creds) else cli_creds


def _atomic_write_app_tokens(tokens: dict[str, Any]) -> None:
    _cache.atomic_write_app_tokens(APP_TOKENS_FILE, tokens)


def _persist_app_credentials(creds: CodexCredentials) -> None:
    with _refresh_guard():
        _atomic_write_app_tokens(_cache.credential_tokens(creds))
        _clear_runtime_auth_failure()


def _clear_app_credentials() -> None:
    with _refresh_guard():
        _mark_runtime_auth_failure()
        _cache.delete_app_tokens(
            APP_TOKENS_FILE, logger=logger, label="could not clear app codex tokens"
        )


def _post_token_refresh(refresh_token: str) -> dict[str, Any]:
    return _tokens.post_token_refresh(
        refresh_token,
        client_id=CLIENT_ID,
        endpoint=TOKEN_ENDPOINT,
        client_factory=httpx.Client,
        dead_errors=_REFRESH_DEAD_ERRORS,
    )


def _apply_refresh_response(old: CodexCredentials, response: dict[str, Any]) -> CodexCredentials:
    return _tokens.apply_refresh_response(
        old, response, account_id_from_token=_account_id_from_id_token
    )


def _refresh_guard() -> AbstractContextManager[bool]:
    return _lock.reentrant_refresh_guard(
        _REFRESH_LOCK,
        APP_TOKENS_FILE.with_name(".codex_refresh.lock"),
        _REFRESH_GUARD_STATE,
    )


def get_fresh_credentials() -> CodexCredentials:
    return _tokens.get_fresh_credentials(
        _tokens.RefreshBindings(
            lock=_refresh_guard(),
            load_credentials=load_credentials,
            post_refresh=_post_token_refresh,
            apply_refresh=_apply_refresh_response,
            persist=_persist_app_credentials,
            mark_failure=_mark_runtime_auth_failure,
            clear_app_credentials=_clear_app_credentials,
        )
    )


def build_codex_auth_url(code_challenge: str) -> tuple[str, str]:
    return _callback.build_auth_url(
        code_challenge,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        auth_endpoint=AUTH_ENDPOINT,
        scopes=OAUTH_SCOPES,
        state_factory=secrets.token_urlsafe,
    )


def make_oauth_callback_handler(expected_state: str) -> type[Any]:
    return _callback.make_strict_callback_handler(
        expected_state, handler_factory=_legacy_callback_handler
    )


def _exchange_code_for_tokens(auth_code: str, code_verifier: str) -> dict[str, Any]:
    return _tokens.exchange_code_for_tokens(
        auth_code,
        code_verifier,
        client_id=CLIENT_ID,
        endpoint=TOKEN_ENDPOINT,
        redirect_uri=REDIRECT_URI,
        urlopen_safe=_urlopen_safe,
    )


def _open_signin_browser(auth_url: str) -> bool:
    return _callback.open_signin_browser(
        auth_url,
        browser_open=webbrowser.open,
        startfile=getattr(os, "startfile", None),
        logger=logger,
    )


run_self_oauth_login = _runtime.run_self_oauth_login
call_codex_model = _runtime.call_codex_model
_stream_codex_round = _runtime.stream_codex_round
call_codex_model_with_tools = _runtime.call_codex_model_with_tools


def _credential_source_path(creds: CodexCredentials) -> Optional[Path]:
    return _cache.credential_source_path(
        creds, cli_path=codex_auth_json_path(), app_path=APP_TOKENS_FILE
    )


def _runtime_failure_superseded_by(creds: CodexCredentials) -> bool:
    return _cache.runtime_failure_superseded(
        _credential_source_path(creds), _RUNTIME_AUTH_FAILURE_AT
    )


credential_status = _runtime.credential_status
build_codex_llm_client = _runtime.build_codex_llm_client
build_codex_librarian_client = _runtime.build_codex_librarian_client
login = _runtime.login
logout = _runtime.logout
reauthenticate = _runtime.reauthenticate
_verify_codex_token = _runtime.verify_codex_token


_load_persisted_runtime_failure()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Codex OAuth — self login")
    try:
        result = login()
        print(f"Connected: {result}")
    except CodexAuthError as exc:
        print(f"Login failed: {exc}")
        raise SystemExit(1)
