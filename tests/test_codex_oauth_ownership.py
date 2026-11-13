"""Credential ownership and platform privacy regressions for Codex OAuth."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import pytest

from olga_companion.llm import codex_oauth
from olga_companion.llm import codex_oauth_cache
from olga_companion.llm import codex_oauth_privacy


def _expiring_jwt() -> str:
    payload = json.dumps({"exp": time.time() + 1}).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"header.{encoded}.signature"


def test_expiring_cli_credentials_are_never_refreshed_or_copied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given an expiring credential owned by the Codex CLI.
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    cli_auth = codex_home / "auth.json"
    cli_auth.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": _expiring_jwt(),
                    "refresh_token": "cli-one-use-refresh",
                    "account_id": "cli-account",
                }
            }
        ),
        encoding="utf-8",
    )
    original = cli_auth.read_bytes()
    app_tokens = tmp_path / "app" / "codex_tokens.json"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", app_tokens)
    monkeypatch.setattr(
        codex_oauth, "_RUNTIME_FAILURE_FILE", tmp_path / "app" / "failure.json"
    )
    refresh_calls: list[str] = []
    monkeypatch.setattr(
        codex_oauth, "_post_token_refresh", lambda token: refresh_calls.append(token)
    )

    # When the app needs a fresh credential.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth.get_fresh_credentials()

    # Then it fails closed with guidance and leaves CLI state strictly read-only.
    assert captured.value.relogin_required is True
    assert str(captured.value) == (
        "codex CLI 로그인이 만료되었습니다. Codex CLI에서 다시 로그인하거나 "
        "앱 로그인을 사용해 주세요."
    )
    assert refresh_calls == []
    assert cli_auth.read_bytes() == original
    assert not app_tokens.exists()


def test_symlinked_app_cache_cannot_reclassify_cli_owned_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given an app-cache symlink aimed at an otherwise external CLI auth file.
    cli_auth = tmp_path / "external-cli-auth.json"
    cli_auth.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": _expiring_jwt(),
                    "refresh_token": "cli-one-use-refresh",
                    "account_id": "cli-account",
                }
            }
        ),
        encoding="utf-8",
    )
    original = cli_auth.read_bytes()
    app_tokens = tmp_path / "app" / "codex_tokens.json"
    app_tokens.parent.mkdir()
    try:
        app_tokens.symlink_to(cli_auth)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    empty_codex_home = tmp_path / "empty-codex-home"
    empty_codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(empty_codex_home))
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", app_tokens)
    refresh_calls: list[str] = []
    monkeypatch.setattr(
        codex_oauth, "_post_token_refresh", lambda token: refresh_calls.append(token)
    )

    # When the app resolves credentials through its owned-cache boundary.
    with pytest.raises(codex_oauth.CodexAuthError, match="로그인이 필요"):
        codex_oauth.get_fresh_credentials()

    # Then the alias is rejected before refresh or mutation of CLI-owned state.
    assert refresh_calls == []
    assert cli_auth.read_bytes() == original
    assert app_tokens.is_symlink()


def test_logout_delete_failure_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given an invalid app-cache directory that cannot be unlinked as a file.
    app_tokens = tmp_path / "tokens.json"
    app_tokens.mkdir()
    monkeypatch.setattr(codex_oauth, "APP_TOKENS_FILE", app_tokens)
    monkeypatch.setattr(
        codex_oauth, "_RUNTIME_FAILURE_FILE", tmp_path / "failure.json"
    )
    marked: list[bool] = []
    cleared: list[bool] = []
    monkeypatch.setattr(
        codex_oauth, "_mark_runtime_auth_failure", lambda: marked.append(True)
    )
    monkeypatch.setattr(
        codex_oauth, "_clear_runtime_auth_failure", lambda: cleared.append(True)
    )

    # When logout cannot remove the owned credential.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth.logout()

    # Then the operation remains failed and the auth state stays latched.
    assert str(captured.value) == (
        "codex 로그아웃에 실패했습니다. 토큰 파일 권한을 확인해 주세요."
    )
    assert marked == [True]
    assert cleared == []


def test_private_atomic_write_fsyncs_file_and_directory_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given isolated private storage and observable sync seams.
    target = tmp_path / "private" / "tokens.json"
    file_syncs: list[int] = []
    directory_syncs: list[Path] = []
    real_fsync = codex_oauth_cache.os.fsync
    real_directory_sync = codex_oauth_cache._fsync_directory

    def sync_file(descriptor: int) -> None:
        file_syncs.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(codex_oauth_cache.os, "fsync", sync_file)
    monkeypatch.setattr(
        codex_oauth_cache,
        "_fsync_directory",
        lambda path: directory_syncs.append(path),
    )

    # When an app credential is atomically committed.
    codex_oauth_cache.atomic_write_app_tokens(target, {"access_token": "secret"})

    # Then file contents are flushed and directory metadata sync is requested.
    assert file_syncs
    assert directory_syncs == [target.parent]
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert target.stat().st_mode & 0o777 == 0o600

    # And the shared directory sync helper opens, flushes, and closes the directory.
    from olga_companion import sidecar_save_as_fsync

    directory_file_descriptors: list[int] = []
    closed: list[int] = []
    monkeypatch.setattr(sidecar_save_as_fsync.os, "open", lambda *_args: 73)
    monkeypatch.setattr(
        sidecar_save_as_fsync.os,
        "fsync",
        lambda descriptor: directory_file_descriptors.append(descriptor),
    )
    monkeypatch.setattr(
        sidecar_save_as_fsync.os, "close", lambda descriptor: closed.append(descriptor)
    )
    real_directory_sync(target.parent)
    assert directory_file_descriptors == [73]
    assert closed == [73]


def test_windows_sid_lookup_uses_system_binary_and_validates_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a whoami result from the Windows system directory.
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class Result:
        returncode = 0
        stdout = '"DOMAIN\\OLGA","S-1-5-21-777"\r\n'

    def run(command: list[str], **kwargs: Any) -> Result:
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(codex_oauth_privacy.subprocess, "run", run)

    # When the current process SID is resolved.
    assert codex_oauth_privacy._windows_current_sid() == "S-1-5-21-777"

    # Then the trusted system executable and non-shell invocation are used.
    assert calls[0][0] == [
        r"C:\Windows\System32\whoami.exe",
        "/user",
        "/fo",
        "csv",
        "/nh",
    ]
    assert calls[0][1]["shell"] is False

    # And malformed identity output fails closed.
    Result.stdout = '"DOMAIN\\OLGA","not-a-sid"\r\n'
    with pytest.raises(OSError, match="owner lookup failed"):
        codex_oauth_privacy._windows_current_sid()


def test_windows_private_acl_disables_inheritance_and_grants_current_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given a deterministic Windows identity and a captured icacls runner.
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class Result:
        returncode = 0

    def run(command: list[str], **kwargs: Any) -> Result:
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(
        codex_oauth_privacy, "_windows_current_sid", lambda: "S-1-5-21-1234"
    )
    monkeypatch.setattr(codex_oauth_privacy.subprocess, "run", run)

    # When app-owned directory and file ACLs are hardened on Windows.
    codex_oauth_cache._harden_private_path(
        tmp_path / "private", directory=True, platform="nt"
    )
    codex_oauth_cache._harden_private_path(
        tmp_path / "private" / "tokens.json", directory=False, platform="nt"
    )

    # Then inherited ACEs are removed and only the current-user grant is added.
    assert calls[0][0] == [
        r"C:\Windows\System32\icacls.exe",
        str(tmp_path / "private"),
        "/inheritance:r",
        "/grant:r",
        "*S-1-5-21-1234:(OI)(CI)F",
    ]
    assert calls[1][0] == [
        r"C:\Windows\System32\icacls.exe",
        str(tmp_path / "private" / "tokens.json"),
        "/inheritance:r",
        "/grant:r",
        "*S-1-5-21-1234:F",
    ]
    assert all("/inheritance:r" in command for command, _kwargs in calls)
    expected_options = {
        "capture_output": True,
        "check": False,
        "shell": False,
        "stdin": codex_oauth_privacy.subprocess.DEVNULL,
        "text": True,
        "timeout": 10,
    }
    assert all(kwargs == expected_options for _, kwargs in calls)

    # And an ACL command failure is surfaced instead of silently weakening privacy.
    Result.returncode = 5
    with pytest.raises(OSError, match="ACL hardening failed"):
        codex_oauth_cache._harden_private_path(
            tmp_path / "private", directory=True, platform="nt"
        )

    # And rejecting directory hardening prevents any secret or temp-file write.
    target = tmp_path / "blocked" / "tokens.json"

    def reject_acl(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("privacy unavailable")

    monkeypatch.setattr(codex_oauth_cache, "_harden_private_path", reject_acl)
    with pytest.raises(OSError, match="privacy unavailable"):
        codex_oauth_cache.atomic_write_app_tokens(
            target, {"access_token": "must-not-land"}
        )
    assert not target.exists()
    assert list(target.parent.glob("*.tmp")) == []
