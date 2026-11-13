"""Refresh concurrency and failure-latch persistence regressions."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from olga_companion.llm import codex_oauth
from olga_companion.llm import codex_oauth_lock
from olga_companion.llm import codex_oauth_tokens


def _jwt_with_expiry(expiry: int) -> str:
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry}).encode()).rstrip(b"=")
    return f"header.{payload.decode()}.signature"


def test_failed_credential_write_does_not_clear_runtime_failure_latch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given a refreshed credential whose durable write fails.
    creds = codex_oauth.CodexCredentials(
        access_token="access",
        refresh_token="refresh",
        account_id="account",
        source="app_oauth",
    )
    cleared: list[bool] = []
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(codex_oauth, "_RUNTIME_FAILURE_FILE", tmp_path / "failure.json")
    monkeypatch.setattr(
        codex_oauth,
        "_atomic_write_app_tokens",
        lambda _tokens: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(codex_oauth, "_clear_runtime_auth_failure", lambda: cleared.append(True))

    # When persistence fails, the caller sees the failure.
    with pytest.raises(OSError, match="disk full"):
        codex_oauth._persist_app_credentials(creds)

    # Then the failure latch was not cleared ahead of durable credentials.
    assert cleared == []


def test_distinct_sidecars_share_one_refresh_critical_section(tmp_path: Path) -> None:
    # Given two logical sidecars with independent thread locks and one lock file.
    stale = codex_oauth.CodexCredentials(
        access_token="not-a-jwt",
        refresh_token="one-use-refresh",
        account_id="account",
        source="app_oauth",
    )
    fresh_access = _jwt_with_expiry(int(time.time()) + 3600)
    state = {"credentials": stale}
    state_lock = threading.Lock()
    first_reads = threading.Barrier(2)
    local = threading.local()
    refresh_count = 0

    def load_credentials() -> codex_oauth.CodexCredentials:
        if not getattr(local, "did_first_read", False):
            local.did_first_read = True
            first_reads.wait(timeout=2)
        with state_lock:
            return state["credentials"]

    def post_refresh(_refresh_token: str) -> dict[str, str]:
        nonlocal refresh_count
        with state_lock:
            refresh_count += 1
        time.sleep(0.05)
        return {"access_token": fresh_access, "refresh_token": "rotated-refresh"}

    def persist(creds: codex_oauth.CodexCredentials) -> None:
        with state_lock:
            state["credentials"] = creds

    lock_path = tmp_path / "codex-refresh.lock"

    def refresh_as_sidecar() -> codex_oauth.CodexCredentials:
        bindings = codex_oauth_tokens.RefreshBindings(
            lock=codex_oauth_lock.InterprocessRefreshLock(lock_path, timeout=2),
            load_credentials=load_credentials,
            post_refresh=post_refresh,
            apply_refresh=codex_oauth._apply_refresh_response,
            persist=persist,
            mark_failure=lambda: None,
            clear_app_credentials=lambda: None,
        )
        return codex_oauth_tokens.get_fresh_credentials(bindings)

    # When both sidecars race to refresh a one-use token.
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: refresh_as_sidecar(), range(2)))

    # Then only one exchange occurs and both observe the rotated credential.
    assert refresh_count == 1
    assert {result.access_token for result in results} == {fresh_access}


def _seed_stale_app_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    app_tokens = tmp_path / "codex_tokens.json"
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", app_tokens)
    monkeypatch.setattr(codex_oauth, "_RUNTIME_FAILURE_FILE", tmp_path / "failure.json")
    monkeypatch.setattr(codex_oauth, "_RUNTIME_AUTH_FAILURE_AT", None)
    monkeypatch.setattr(codex_oauth, "_load_codex_cli_credentials", lambda: None)
    codex_oauth._atomic_write_app_tokens(
        {
            "access_token": "old-access",
            "refresh_token": "one-use-refresh",
            "account_id": "old-acct",
        }
    )
    return app_tokens


def test_logout_cannot_race_with_refresh_and_resurrect_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a refresh paused after rotating the old account's one-use token.
    app_tokens = _seed_stale_app_cache(tmp_path, monkeypatch)
    refresh_paused = threading.Event()
    resume_refresh = threading.Event()
    logout_started = threading.Event()

    def post_refresh(_token: str) -> dict[str, str]:
        refresh_paused.set()
        assert resume_refresh.wait(timeout=2)
        return {"access_token": "rotated-old", "refresh_token": "rotated-refresh"}

    monkeypatch.setattr(codex_oauth, "_post_token_refresh", post_refresh)

    def logout() -> None:
        logout_started.set()
        codex_oauth.logout()

    # When logout starts while refresh owns the credential mutation boundary.
    with ThreadPoolExecutor(max_workers=2) as executor:
        refresh_future = executor.submit(codex_oauth.get_fresh_credentials)
        assert refresh_paused.wait(timeout=2)
        logout_future = executor.submit(logout)
        assert logout_started.wait(timeout=2)
        time.sleep(0.05)
        logout_was_serialized = not logout_future.done()
        resume_refresh.set()
        refresh_future.result(timeout=2)
        logout_future.result(timeout=2)

    # Then logout runs last and the old credential cannot reappear.
    assert logout_was_serialized is True
    assert not app_tokens.exists()


def test_new_login_cannot_be_overwritten_by_inflight_old_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an old-account refresh paused while a new account logs in.
    _seed_stale_app_cache(tmp_path, monkeypatch)
    refresh_paused = threading.Event()
    resume_refresh = threading.Event()
    login_started = threading.Event()

    def post_refresh(_token: str) -> dict[str, str]:
        refresh_paused.set()
        assert resume_refresh.wait(timeout=2)
        return {"access_token": "rotated-old", "refresh_token": "rotated-refresh"}

    monkeypatch.setattr(codex_oauth, "_post_token_refresh", post_refresh)
    new_login = codex_oauth.CodexCredentials(
        access_token="new-access",
        refresh_token="new-refresh",
        account_id="new-acct",
        source="app_oauth",
    )

    def persist_new_login() -> None:
        login_started.set()
        codex_oauth._persist_app_credentials(new_login)

    # When new-login persistence starts during the old refresh.
    with ThreadPoolExecutor(max_workers=2) as executor:
        refresh_future = executor.submit(codex_oauth.get_fresh_credentials)
        assert refresh_paused.wait(timeout=2)
        login_future = executor.submit(persist_new_login)
        assert login_started.wait(timeout=2)
        time.sleep(0.05)
        login_was_serialized = not login_future.done()
        resume_refresh.set()
        refresh_future.result(timeout=2)
        login_future.result(timeout=2)

    # Then the deliberate login commits last and retains the new account.
    final = codex_oauth._load_app_credentials()
    assert login_was_serialized is True
    assert final is not None
    assert final.account_id == "new-acct"


def test_status_compare_clear_cannot_erase_a_newer_failure_latch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a stale latch whose supersede check pauses before clearing it.
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", tmp_path / "tokens.json")
    failure_file = tmp_path / "failure.json"
    monkeypatch.setattr(codex_oauth, "_RUNTIME_FAILURE_FILE", failure_file)
    creds = codex_oauth.CodexCredentials(
        access_token="access",
        refresh_token="refresh",
        account_id="account",
        source="app_oauth",
    )
    monkeypatch.setattr(codex_oauth, "load_credentials", lambda: creds)
    codex_oauth._mark_runtime_auth_failure()
    compare_started = threading.Event()
    resume_compare = threading.Event()

    def superseded(_creds: codex_oauth.CodexCredentials) -> bool:
        compare_started.set()
        assert resume_compare.wait(timeout=2)
        return True

    monkeypatch.setattr(codex_oauth, "_runtime_failure_superseded_by", superseded)

    # When a newer 401 marker arrives during the compare-and-clear sequence.
    with ThreadPoolExecutor(max_workers=2) as executor:
        status_future = executor.submit(codex_oauth.credential_status)
        assert compare_started.wait(timeout=2)
        mark_future = executor.submit(codex_oauth._mark_runtime_auth_failure)
        time.sleep(0.05)
        mark_was_serialized = not mark_future.done()
        resume_compare.set()
        status_future.result(timeout=2)
        mark_future.result(timeout=2)

    # Then the new marker survives in memory and persisted state.
    assert mark_was_serialized is True
    assert codex_oauth._RUNTIME_AUTH_FAILURE_AT is not None
    assert failure_file.is_file()
