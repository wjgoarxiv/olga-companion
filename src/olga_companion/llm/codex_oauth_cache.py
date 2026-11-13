"""Local credential loading, precedence, persistence, and failure markers."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from .codex_oauth_models import CodexCredentials
from .codex_oauth_privacy import harden_private_path as _harden_private_path


def credentials_from_tokens(
    tokens: Mapping[str, Any],
    *,
    source: str,
    account_id_from_token: Callable[[str], str | None],
) -> CodexCredentials | None:
    """Parse locally trusted token data into a usable credential."""
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        return None
    if not isinstance(refresh_token, str) or not refresh_token:
        return None
    raw_id_token = tokens.get("id_token")
    id_token = raw_id_token if isinstance(raw_id_token, str) else ""
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        account_id = account_id_from_token(id_token)
    if not account_id:
        account_id = account_id_from_token(access_token)
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token,
        account_id=account_id,
        source=source,
    )


def load_credentials_file(
    path: Path,
    *,
    warning_label: str,
    logger: logging.Logger,
    parser: Callable[[Mapping[str, Any]], CodexCredentials | None],
    private_owned: bool = False,
) -> CodexCredentials | None:
    """Load a credential file, failing closed on absent or malformed data."""
    try:
        if not path.is_file():
            return None
        if private_owned:
            _reject_owned_symlink(path)
            _harden_private_path(path.parent, directory=True)
            _harden_private_path(path, directory=False)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (
        OSError,
        RecursionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
    ) as exc:
        logger.warning("%s unreadable: %s", warning_label, type(exc).__name__)
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict):
        return None
    return parser(tokens)


def expiry_sort_key(creds: CodexCredentials | None) -> float:
    """Return a sortable expiry, placing missing/malformed expiry last."""
    if creds is None or creds.expires_at is None:
        return float("-inf")
    return creds.expires_at


def choose_credentials(
    cli_creds: CodexCredentials | None,
    app_creds: CodexCredentials | None,
) -> CodexCredentials | None:
    """Prefer a deliberate live app login, otherwise the freshest source."""
    if cli_creds is None:
        return app_creds
    if app_creds is None:
        return cli_creds
    if not app_creds.is_expiring():
        return app_creds
    if expiry_sort_key(app_creds) > expiry_sort_key(cli_creds):
        return app_creds
    return cli_creds


def atomic_write_app_tokens(path: Path, tokens: Mapping[str, Any]) -> None:
    """Write app-owned credentials atomically with mode 0600."""
    _atomic_write_json(
        path,
        {"tokens": tokens},
        prefix=".olga_copilot_codex_tokens.",
    )


def _atomic_write_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    prefix: str,
) -> None:
    """Atomically replace one private JSON file after flushing its contents."""
    _reject_owned_symlink(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _reject_owned_symlink(path)
    _harden_private_path(path.parent, directory=True)
    serialized = json.dumps(payload, indent=2)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=prefix,
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        _harden_private_path(Path(tmp_path), directory=False)
        os.replace(tmp_path, path)
    except (OSError, RecursionError, TypeError, ValueError):
        with suppress(OSError):
            os.unlink(tmp_path)
        raise
    _fsync_directory(path.parent)


def _reject_owned_symlink(path: Path) -> None:
    """Keep app-owned state out of symlinked files or storage directories."""
    if path.is_symlink() or path.parent.is_symlink():
        raise OSError("app credential-store symlinks are not allowed")


def _fsync_directory(path: Path) -> None:
    """Flush directory metadata after replace or unlink."""
    from ..sidecar_save_as_fsync import fsync_directory

    fsync_directory(path)


def credential_tokens(creds: CodexCredentials) -> dict[str, str | None]:
    """Return the on-disk token shape; callers must never log it."""
    return {
        "access_token": creds.access_token,
        "refresh_token": creds.refresh_token,
        "id_token": creds.id_token,
        "account_id": creds.account_id,
    }


def delete_app_tokens(path: Path, *, logger: logging.Logger, label: str) -> bool:
    """Best-effort deletion of the app-owned cache only."""
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError as exc:
        logger.warning("%s: %s", label, type(exc).__name__)
        return False
    _fsync_directory(path.parent)
    return True


def write_runtime_failure(path: Path, failed_at: float) -> bool:
    """Best-effort persistence of the runtime authentication latch."""
    try:
        _atomic_write_json(
            path,
            {"failed_at": failed_at},
            prefix=".olga_copilot_codex_failure.",
        )
    except (OSError, RecursionError, TypeError, ValueError):
        return False
    return True


def delete_runtime_failure(path: Path) -> bool:
    """Best-effort deletion of the persisted runtime failure latch."""
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    _fsync_directory(path.parent)
    return True


def load_runtime_failure(path: Path) -> float | None:
    """Load a positive persisted failure timestamp, when valid."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        timestamp = float(data.get("failed_at"))
    except (
        OSError,
        RecursionError,
        ValueError,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ):
        return None
    return timestamp if timestamp > 0 else None


def credential_source_path(
    creds: CodexCredentials,
    *,
    cli_path: Path,
    app_path: Path,
) -> Path | None:
    """Return the owned source path used for staleness checks."""
    if creds.source == "codex_cli":
        return cli_path
    if creds.source == "app_oauth":
        return app_path
    return None


def runtime_failure_superseded(path: Path | None, failed_at: float | None) -> bool:
    """Return whether a credential file was rewritten after a failure."""
    if path is None or failed_at is None:
        return False
    try:
        return path.stat().st_mtime > failed_at
    except OSError:
        return False
