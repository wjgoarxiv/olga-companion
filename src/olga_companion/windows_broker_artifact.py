"""Broker build-cache and per-run immutable request preparation."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .windows_broker_protocol import (
    BROKER_EXE_NAME,
    BROKER_PROTOCOL,
    CANCEL_NAME,
    FIXED_CASE_NAME,
    REQUEST_NAME,
    STATUS_NAME,
    BrokerArtifact,
    BrokerUnavailable,
    PreparedBrokerRun,
)

PathHasher = Callable[[Path], str]
SourceHasher = Callable[[tuple[Path, ...]], str]
CompilerCommand = Callable[[Path, Path, tuple[Path, ...]], list[str]]
PathEncoder = Callable[[Path], str]
DispatchCommand = Callable[[Path], list[str]]
JsonWriter = Callable[[Path, Mapping[str, Any]], None]

_FIXED_CASE_MESSAGE = (
    "Native broker case must use the fixed contained staged name case.genkey."
)
_TIMEOUT_MESSAGE = "Broker timeout must be positive."
_ENGINE_CHANGED_MESSAGE = (
    "Native engine content changed before broker request creation."
)
_CASE_CHANGED_MESSAGE = "Staged case content changed before broker request creation."
_BROKER_CHANGED_MESSAGE = (
    "Per-run broker copy does not match the approved broker identity."
)


def _remove_temporary(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def ensure_broker_artifact(
    *,
    capability: Mapping[str, Any],
    sources: tuple[Path, ...],
    csc: Path,
    cache_root: Path,
    sha256: PathHasher,
    source_sha256: SourceHasher,
    compiler_command: CompilerCommand,
    atomic_json: JsonWriter,
) -> BrokerArtifact:
    """Build or reuse the content-addressed broker executable."""
    if not capability["available"]:
        raise BrokerUnavailable(str(capability["reason"]))
    source_digest = source_sha256(sources)
    compiler_sha256 = sha256(csc)
    build_material = json.dumps(
        {
            "protocol": BROKER_PROTOCOL,
            "source_sha256": source_digest,
            "compiler_sha256": compiler_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    build_id = hashlib.sha256(build_material.encode("utf-8")).hexdigest()
    cache_dir = cache_root / "control" / "windows-broker" / build_id
    target = cache_dir / BROKER_EXE_NAME
    identity_path = cache_dir / "identity.json"
    if target.is_file() and identity_path.is_file():
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            target_sha256 = sha256(target)
        except (OSError, json.JSONDecodeError):
            identity = {}
            target_sha256 = ""
        if (
            identity.get("build_id") == build_id
            and identity.get("sha256") == target_sha256
            and identity.get("protocol") == BROKER_PROTOCOL
        ):
            return BrokerArtifact(target, target_sha256, source_digest, build_id)

    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = cache_dir / ("." + BROKER_EXE_NAME + "." + uuid.uuid4().hex + ".tmp")
    command = compiler_command(csc, temporary, sources)
    try:
        # csc.exe writes diagnostics in the Windows OEM code page, not UTF-8: decode
        # leniently so a Korean-locale message cannot turn a compiler error into a crash.
        result = subprocess.run(command, capture_output=True, timeout=60, check=False)
        if result.returncode != 0 or not temporary.is_file():
            detail = (
                (result.stderr or result.stdout).decode("utf-8", errors="replace")
                or "compiler produced no executable"
            ).strip()[-2000:]
            raise BrokerUnavailable(
                "Could not build the Explorer broker with Framework64 csc.exe: "
                + detail
            )
        os.replace(temporary, target)
        target_sha256 = sha256(target)
        atomic_json(
            identity_path,
            {
                "build_id": build_id,
                "protocol": BROKER_PROTOCOL,
                "sha256": target_sha256,
                "source_sha256": source_digest,
                "compiler_sha256": compiler_sha256,
            },
        )
        return BrokerArtifact(target, target_sha256, source_digest, build_id)
    finally:
        _remove_temporary(temporary)


def prepare_broker_run_artifact(
    *,
    run_dir: Path,
    artifact: BrokerArtifact,
    engine: Path,
    engine_sha256: str,
    staged_case: Path,
    staged_case_sha256: str,
    timeout_s: int,
    file_sha256: PathHasher,
    broker_sha256: PathHasher,
    windows_path: PathEncoder,
    dispatch_command: DispatchCommand,
    atomic_json: JsonWriter,
) -> PreparedBrokerRun:
    """Copy the broker and write its exact, immutable per-run request."""
    run_root = run_dir.resolve()
    if staged_case.resolve().parent != run_root or staged_case.name != FIXED_CASE_NAME:
        raise ValueError(_FIXED_CASE_MESSAGE)
    if timeout_s <= 0:
        raise ValueError(_TIMEOUT_MESSAGE)
    if file_sha256(engine) != engine_sha256:
        raise ValueError(_ENGINE_CHANGED_MESSAGE)
    if file_sha256(staged_case) != staged_case_sha256:
        raise ValueError(_CASE_CHANGED_MESSAGE)
    broker_path = run_dir / BROKER_EXE_NAME
    shutil.copy2(artifact.path, broker_path)
    if broker_sha256(broker_path) != artifact.sha256:
        raise ValueError(_BROKER_CHANGED_MESSAGE)

    request_id = secrets.token_hex(32)
    request_path = run_dir / REQUEST_NAME
    status_path = run_dir / STATUS_NAME
    cancel_path = run_dir / CANCEL_NAME
    expires = datetime.now(timezone.utc) + timedelta(minutes=2)
    request = {
        "protocol": artifact.protocol,
        "token": secrets.token_hex(32),
        "request_id": request_id,
        "expires_utc": expires.isoformat().replace("+00:00", "Z"),
        "run_dir": windows_path(run_dir),
        "engine": windows_path(engine),
        "engine_sha256": engine_sha256,
        "broker_sha256": artifact.sha256,
        "staged_case": FIXED_CASE_NAME,
        "staged_case_sha256": staged_case_sha256,
        "argv": [FIXED_CASE_NAME],
        "timeout_s": int(timeout_s),
    }
    atomic_json(request_path, request)
    request_path.chmod(
        request_path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    )
    return PreparedBrokerRun(
        broker_path=broker_path,
        request_path=request_path,
        status_path=status_path,
        cancel_path=cancel_path,
        request_id=request_id,
        dispatch_command=dispatch_command(broker_path),
    )
