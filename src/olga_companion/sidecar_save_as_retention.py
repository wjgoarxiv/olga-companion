"""Globally bounded, cross-process retention for Save As safety captures."""

from __future__ import annotations

import errno
import json
import os
import secrets
import stat
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from . import config
from .private_path_acl import harden_private_path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_RETENTION_PREFIX = ".olga-companion-retained-"
_MAX_RETENTION_BYTES = 512 * 1024 * 1024
_MAX_RETENTION_FILES = 128
_MAX_RETENTION_DIRECTORIES = 64
_MAX_REGISTRY_BYTES = 64 * 1024
_LOCK_TIMEOUT_SECONDS = 45.0
_LOCK_POLL_SECONDS = 0.05
_LOCAL_LOCK = threading.RLock()
_LOCAL_STATE = threading.local()
_STATE_ROOT = Path.home() / ".olga_copilot" / "save-as-retention"


def _retention_full() -> OSError:
    return OSError(errno.ENOSPC, "Save As retention capacity is full.")


def _state_root() -> Path:
    root = _STATE_ROOT
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    harden_private_path(root, directory=True)
    return root


def _registry_path() -> Path:
    return _state_root() / "registry.json"


def _lock_path() -> Path:
    return _state_root() / "retention.lock"


class _InterprocessRetentionLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: BinaryIO | None = None

    def __enter__(self) -> None:
        if self._path.is_symlink():
            raise _retention_full()
        handle = self._path.open("a+b")
        try:
            harden_private_path(self._path, directory=False)
        except OSError:
            handle.close()
            raise
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise OSError(
                    errno.ETIMEDOUT,
                    "Save As retention lock timed out.",
                )
            time.sleep(_LOCK_POLL_SECONDS)
        self._handle = handle

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()


def _try_lock(handle: BinaryIO) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _retention_state_guard() -> Iterator[None]:
    depth = getattr(_LOCAL_STATE, "depth", 0)
    if depth:
        _LOCAL_STATE.depth = depth + 1
        try:
            yield
        finally:
            _LOCAL_STATE.depth -= 1
        return
    with _LOCAL_LOCK:
        with _InterprocessRetentionLock(_lock_path()):
            _LOCAL_STATE.depth = 1
            try:
                yield
            finally:
                _LOCAL_STATE.depth = 0


def _load_registry() -> list[Path]:
    path = _registry_path()
    if path.is_symlink():
        raise _retention_full()
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_REGISTRY_BYTES + 1)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise _retention_full() from exc
    if len(raw) > _MAX_REGISTRY_BYTES:
        raise _retention_full()
    try:
        record = json.loads(raw)
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _retention_full() from exc
    if not isinstance(record, dict) or set(record) != {"version", "directories"}:
        raise _retention_full()
    values = record.get("directories")
    if record.get("version") != 1 or not isinstance(values, list):
        raise _retention_full()
    if len(values) > _MAX_RETENTION_DIRECTORIES:
        raise _retention_full()
    directories: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value or "\0" in value:
            raise _retention_full()
        directory = Path(value)
        if not directory.is_absolute() or not directory.name.startswith(
            _RETENTION_PREFIX
        ):
            raise _retention_full()
        directories.append(directory)
    if len(set(directories)) != len(directories):
        raise _retention_full()
    return directories


def _write_registry(directories: Sequence[Path]) -> None:
    path = _registry_path()
    if path.is_symlink():
        raise _retention_full()
    payload = json.dumps(
        {"version": 1, "directories": [str(directory) for directory in directories]},
        sort_keys=True,
        separators=(",", ":"),
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".save-as-retention.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        harden_private_path(temporary, directory=False)
        os.replace(temporary, path)
        temporary = None
        harden_private_path(path, directory=False)
        config._fsync_parent_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _retained_usage(directories: Sequence[Path]) -> tuple[int, int, int]:
    file_count = 0
    byte_count = 0
    try:
        for directory in directories:
            try:
                metadata = directory.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                raise _retention_full()
            with os.scandir(directory) as children:
                for child in children:
                    metadata = child.stat(follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode):
                        raise _retention_full()
                    file_count += 1
                    byte_count += metadata.st_size
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise
        raise _retention_full() from exc
    return len(directories), file_count, byte_count


def _ensure_capacity(directories: Sequence[Path], required_bytes: int) -> None:
    if required_bytes < 0:
        raise OSError(errno.EINVAL, "Save As retention request cannot be negative.")
    directory_count, file_count, byte_count = _retained_usage(directories)
    if (
        byte_count + required_bytes > _MAX_RETENTION_BYTES
        or file_count + 2 > _MAX_RETENTION_FILES
        or directory_count + 1 > _MAX_RETENTION_DIRECTORIES
    ):
        raise _retention_full()


@contextmanager
def retention_capacity_guard(required_bytes: int) -> Iterator[None]:
    """Serialize publication globally and fail before it could exceed the cap."""
    with _retention_state_guard():
        _ensure_capacity(_load_registry(), required_bytes)
        yield


def _retention_base(destination: Path) -> Path:
    parent = destination.parent
    candidate = parent.parent
    try:
        if candidate.stat().st_dev != parent.stat().st_dev:
            candidate = parent
    except OSError:
        candidate = parent
    return candidate


def allocate_retention_root(destination: Path, required_bytes: int) -> Path:
    """Write-ahead register and create one same-filesystem capture directory."""
    with _retention_state_guard():
        directories = _load_registry()
        _ensure_capacity(directories, required_bytes)
        base = _retention_base(destination)
        for _ in range(32):
            root = base / f"{_RETENTION_PREFIX}{secrets.token_hex(8)}"
            if os.path.lexists(root):
                continue
            _write_registry([*directories, root])
            root.mkdir(mode=0o700)
            harden_private_path(root, directory=True)
            return root
    raise OSError(errno.EEXIST, "Could not allocate Save As retention storage.")
