"""Compatibility facade for the native Windows Explorer broker."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Final

from . import windows_broker_artifact as _artifact
from . import windows_broker_process as _process
from . import windows_broker_protocol as _protocol
from . import windows_broker_status as _status
from .config import sandbox_root
from .genkey_static import file_sha256

BROKER_PROTOCOL = _protocol.BROKER_PROTOCOL
BROKER_EXE_NAME = _protocol.BROKER_EXE_NAME
REQUEST_NAME = _protocol.REQUEST_NAME
CLAIMED_REQUEST_NAME = _protocol.CLAIMED_REQUEST_NAME
STATUS_NAME = _protocol.STATUS_NAME
CANCEL_NAME = _protocol.CANCEL_NAME
FIXED_CASE_NAME = _protocol.FIXED_CASE_NAME
MAX_BROKER_JSON_BYTES = _protocol.MAX_BROKER_JSON_BYTES
DEFAULT_STARTUP_TIMEOUT_S = _protocol.DEFAULT_STARTUP_TIMEOUT_S
DEFAULT_HEARTBEAT_TIMEOUT_S = _protocol.DEFAULT_HEARTBEAT_TIMEOUT_S

CSC_PATH = Path("/mnt/c/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
EXPLORER_PATH = Path("/mnt/c/Windows/explorer.exe")
WSL_INIT_PATH = Path("/init")
BROKER_SOURCE_NAMES: Final = (
    "OlgaExplorerBroker.cs",
    "OlgaExplorerBroker.Native.cs",
    "OlgaExplorerBroker.Protocol.cs",
)

BrokerUnavailable = _protocol.BrokerUnavailable
BrokerArtifact = _protocol.BrokerArtifact
PreparedBrokerRun = _protocol.PreparedBrokerRun
BrokerProcess = _process.BrokerProcess

_atomic_json = _protocol._atomic_json
_read_status = _status._read_status
read_broker_status = _status.read_broker_status
broker_heartbeat_is_live = _status.broker_heartbeat_is_live
request_broker_cancel = _status.request_broker_cancel
qualify_native_completion = _status.qualify_native_completion

__all__ = [
    "BROKER_EXE_NAME",
    "BROKER_PROTOCOL",
    "CANCEL_NAME",
    "CLAIMED_REQUEST_NAME",
    "CSC_PATH",
    "DEFAULT_HEARTBEAT_TIMEOUT_S",
    "DEFAULT_STARTUP_TIMEOUT_S",
    "EXPLORER_PATH",
    "FIXED_CASE_NAME",
    "MAX_BROKER_JSON_BYTES",
    "REQUEST_NAME",
    "STATUS_NAME",
    "WSL_INIT_PATH",
    "BrokerArtifact",
    "BrokerProcess",
    "BrokerUnavailable",
    "PreparedBrokerRun",
    "broker_capability",
    "broker_heartbeat_is_live",
    "ensure_broker",
    "prepare_broker_run",
    "qualify_native_completion",
    "read_broker_status",
    "request_broker_cancel",
]


def _source_paths() -> tuple[Path, ...]:
    source_dir = Path(__file__).with_name("broker")
    return tuple(source_dir / name for name in BROKER_SOURCE_NAMES)


def _source_sha256(sources: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        name = source.name.encode("utf-8")
        payload = source.read_bytes()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _native_windows() -> bool:
    return sys.platform == "win32"


def _runtime_paths() -> dict[str, Path | bool]:
    if _native_windows():
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        return {
            "native": True,
            "csc": system_root
            / "Microsoft.NET"
            / "Framework64"
            / "v4.0.30319"
            / "csc.exe",
            "explorer": system_root / "explorer.exe",
            "init": Path(),
        }
    return {
        "native": False,
        "csc": CSC_PATH,
        "explorer": EXPLORER_PATH,
        "init": WSL_INIT_PATH,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _windows_path(path: Path) -> str:
    value = str(path.resolve())
    parts = Path(value).parts
    if (
        len(parts) >= 4
        and parts[1] == "mnt"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    ):
        return parts[2].upper() + ":\\" + "\\".join(parts[3:])
    return value.replace("/", "\\") if _native_windows() else value


def _require_windows_visible(path: Path) -> None:
    """Windows programs resolve a bare Linux path against the current drive root
    (/tmp/x became C:\\tmp\\x, which does not exist), so refuse instead of guessing."""
    if _native_windows():
        return
    parts = path.resolve().parts
    if not (len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1 and parts[2].isalpha()):
        raise BrokerUnavailable(
            "The Explorer broker needs its files on a Windows drive (/mnt/<drive>); "
            "the configured sandbox is Linux-only."
        )


def _compiler_command(
    csc: Path,
    output: Path,
    sources: tuple[Path, ...],
) -> list[str]:
    arguments = [
        "/nologo",
        "/target:exe",
        "/platform:x64",
        "/optimize+",
        "/reference:System.Web.Extensions.dll",
        "/out:" + _windows_path(output),
        *(_windows_path(source) for source in sources),
    ]
    if _native_windows():
        return [str(csc), *arguments]
    return [str(WSL_INIT_PATH), str(csc), str(csc), *arguments]


def _dispatch_command(broker_path: Path) -> list[str]:
    paths = _runtime_paths()
    if paths["native"]:
        return [str(paths["explorer"]), _windows_path(broker_path)]
    explorer = str(paths["explorer"])
    return [str(paths["init"]), explorer, explorer, _windows_path(broker_path)]


def broker_capability() -> dict[str, Any]:
    missing: list[str] = []
    paths = _runtime_paths()
    if not (_native_windows() or sys.platform.startswith("linux")):
        missing.append("native Windows or WSL host")
    required = [("Explorer", paths["explorer"]), ("Framework64 csc.exe", paths["csc"])]
    if not paths["native"]:
        required.insert(0, ("/init", paths["init"]))
    for label, path in required:
        assert isinstance(path, Path)
        if not path.is_file():
            missing.append(label)
    if not all(source.is_file() for source in _source_paths()):
        missing.append("checked-in broker source")
    return {
        "available": not missing,
        "protocol": BROKER_PROTOCOL,
        "strategy": "explorer_one_shot_broker",
        "missing": missing,
        "reason": (
            "Explorer one-shot broker prerequisites are available."
            if not missing
            else "Explorer one-shot broker is unavailable: " + ", ".join(missing) + "."
        ),
    }


def ensure_broker() -> BrokerArtifact:
    capability = broker_capability()
    if not capability["available"]:
        raise BrokerUnavailable(str(capability["reason"]))
    paths = _runtime_paths()
    csc = paths["csc"]
    assert isinstance(csc, Path)
    _require_windows_visible(sandbox_root())
    for source in _source_paths():
        _require_windows_visible(source)
    return _artifact.ensure_broker_artifact(
        capability=capability,
        sources=_source_paths(),
        csc=csc,
        cache_root=sandbox_root(),
        sha256=_sha256,
        source_sha256=_source_sha256,
        compiler_command=_compiler_command,
        atomic_json=_atomic_json,
    )


def prepare_broker_run(
    *,
    run_dir: Path,
    artifact: BrokerArtifact,
    engine: Path,
    engine_sha256: str,
    staged_case: Path,
    staged_case_sha256: str,
    timeout_s: int,
) -> PreparedBrokerRun:
    return _artifact.prepare_broker_run_artifact(
        run_dir=run_dir,
        artifact=artifact,
        engine=engine,
        engine_sha256=engine_sha256,
        staged_case=staged_case,
        staged_case_sha256=staged_case_sha256,
        timeout_s=timeout_s,
        file_sha256=file_sha256,
        broker_sha256=_sha256,
        windows_path=_windows_path,
        dispatch_command=_dispatch_command,
        atomic_json=_atomic_json,
    )
