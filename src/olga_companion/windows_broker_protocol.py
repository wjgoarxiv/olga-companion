"""Shared values and bounded control-file primitives for the Windows broker."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

BROKER_PROTOCOL = "olga-explorer-broker.v1"
BROKER_EXE_NAME = "olga-explorer-broker.exe"
REQUEST_NAME = "broker-request.json"
CLAIMED_REQUEST_NAME = "broker-request.claimed.json"
STATUS_NAME = "broker-status.json"
CANCEL_NAME = "broker-cancel.json"
FIXED_CASE_NAME = "case.genkey"
MAX_BROKER_JSON_BYTES = 64 * 1024
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_HEARTBEAT_TIMEOUT_S = 5.0
_BOUNDED_PAYLOAD_MESSAGE = "Broker control JSON exceeds the bounded payload limit."


class BrokerUnavailable(RuntimeError):
    """The native Explorer broker cannot be used on this host."""


@dataclass(frozen=True, slots=True)
class BrokerArtifact:
    path: Path
    sha256: str
    source_sha256: str
    build_id: str
    protocol: str = BROKER_PROTOCOL

    def to_dict(self) -> dict[str, str]:
        return {
            "protocol": self.protocol,
            "build_id": self.build_id,
            "source_sha256": self.source_sha256,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PreparedBrokerRun:
    broker_path: Path
    request_path: Path
    status_path: Path
    cancel_path: Path
    request_id: str
    dispatch_command: list[str]


def _remove_temporary(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    payload = (
        json.dumps(dict(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    if len(payload.encode("utf-8")) > MAX_BROKER_JSON_BYTES:
        raise ValueError(_BOUNDED_PAYLOAD_MESSAGE)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        _remove_temporary(temporary)
