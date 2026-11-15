"""Owner API-key connections. The key is write-only and never returned."""

from __future__ import annotations

import ctypes
import ipaddress
import json
import logging
import os
import re
import sys
import tempfile
import threading
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .. import config, net
from ..runtime_logging import LOGGER_NAME

_SUPPORTED_PROTOCOLS = frozenset({"openai-chat", "openai-responses"})
_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1"})
_ID = re.compile(r"[0-9a-f]{32}")
_LOCK = threading.Lock()
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


class ApiKeyRejected(ValueError):
    """A save request failed a named contract check."""

    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


class ApiKeyLookupError(LookupError):
    """The connection id is not in the non-secret catalog."""


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def metadata_path() -> Path:
    """Non-secret connection catalog, beside llm-selection.json."""
    return config.project_root() / "var" / "apikey-connections.json"


def _windows_credential_store() -> bool:
    return sys.platform == "win32"


def _credential_target(connection_id: str) -> str:
    return f"OLGA Companion/apikey/{connection_id}"


def _advapi32() -> Any:
    return ctypes.WinDLL("advapi32")


def _cred_write(target: str, secret: str) -> None:
    blob = secret.encode("utf-8")
    buffer = ctypes.create_string_buffer(blob)
    credential = _CREDENTIALW()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = ""
    if not _advapi32().CredWriteW(ctypes.byref(credential), 0):
        raise OSError(ctypes.get_last_error())


def _cred_read(target: str) -> str:
    library = _advapi32()
    pointer = ctypes.POINTER(_CREDENTIALW)()
    if not library.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        raise OSError(ctypes.get_last_error())
    try:
        credential = pointer.contents
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
    finally:
        library.CredFree(pointer)
    return raw.decode("utf-8")


def _cred_delete(target: str) -> None:
    if not _advapi32().CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
        error = ctypes.get_last_error()
        if error not in {0, 2, 1168}:
            raise OSError(error)


def _secret_path(connection_id: str) -> Path:
    return config.private_state_root() / "apikeys" / connection_id


def _store_secret(connection_id: str, secret: str) -> None:
    if _windows_credential_store():
        _cred_write(_credential_target(connection_id), secret)
        return
    path = _secret_path(connection_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, secret.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _read_secret(connection_id: str) -> str:
    if _windows_credential_store():
        return _cred_read(_credential_target(connection_id))
    return _secret_path(connection_id).read_text(encoding="utf-8")


def _delete_secret(connection_id: str) -> None:
    if _windows_credential_store():
        _cred_delete(_credential_target(connection_id))
        return
    _secret_path(connection_id).unlink(missing_ok=True)


def _has_secret(connection_id: str) -> bool:
    try:
        return bool(_read_secret(connection_id))
    except (OSError, UnicodeError, ValueError):
        return False


def _load() -> list[dict[str, Any]]:
    path = metadata_path()
    if not path.is_file():
        return []
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    connections = record.get("connections") if isinstance(record, dict) else None
    if not isinstance(connections, list):
        return []
    return [item for item in connections if isinstance(item, dict)]


def _write(connections: list[dict[str, Any]]) -> None:
    path = metadata_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"connections": connections}, sort_keys=True).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".apikey-", suffix=".tmp")
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _find(connection_id: str) -> dict[str, Any] | None:
    if _ID.fullmatch(connection_id) is None:
        return None
    return next((item for item in _load() if item.get("id") == connection_id), None)


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "label": record["label"],
        "protocol": record["protocol"],
        "base_url": record["base_url"],
        "model": record["model"],
        "has_key": _has_secret(str(record["id"])),
        "last4": record["last4"],
        "verified": bool(record.get("verified")),
        "last_outcome": record.get("last_outcome"),
    }


def list_connections() -> list[dict[str, Any]]:
    with _LOCK:
        return [_public(item) for item in _load()]


def catalog_entries() -> list[dict[str, str]]:
    """Verified connections the chat picker may offer."""
    return [
        {"id": item["id"], "label": item["label"], "tier": "standard"}
        for item in list_connections()
        if item["verified"] and item["has_key"]
    ]


def _reject(outcome: str) -> None:
    raise ApiKeyRejected(outcome)


def _check_protocol(value: object) -> str:
    if value not in _SUPPORTED_PROTOCOLS:
        _reject("unsupported_protocol")
    return str(value)


def _check_label(value: object) -> str:
    if not isinstance(value, str):
        _reject("invalid_label")
    text = value.strip()
    if not text or len(text) > 40 or any(ord(character) < 32 for character in text):
        _reject("invalid_label")
    return text


def _check_base_url(value: object) -> str:
    if not isinstance(value, str):
        _reject("invalid_base_url")
    text = value.strip()
    if not text or len(text) > 200 or any(ord(character) < 32 for character in text):
        _reject("invalid_base_url")
    parsed = urlsplit(text)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        _reject("invalid_base_url")
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in _LOCAL_HTTP_HOSTS:
        _reject("insecure_scheme")
    if parsed.scheme not in {"https", "http"} or not host:
        _reject("invalid_base_url")
    try:
        port = parsed.port
    except ValueError:
        _reject("invalid_base_url")
    if port is not None and not 0 < port < 65536:
        _reject("invalid_base_url")
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            _reject("invalid_base_url")
    elif not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]*[A-Za-z0-9])?", host):
        _reject("invalid_base_url")
    return text


def _check_model(value: object) -> str:
    if not isinstance(value, str):
        _reject("missing_model")
    text = value.strip()
    if not text or len(text) > 128 or any(character.isspace() for character in text):
        _reject("missing_model")
    return text


def _check_key(value: object) -> str:
    if not isinstance(value, str):
        _reject("missing_key")
    text = value.strip()
    if not text:
        _reject("missing_key")
    return text


def _last4(secret: str) -> str:
    """A display suffix. A key of four characters or fewer is not copied here."""
    if len(secret) <= 4:
        return ""
    return secret[-4:]


def save_connection(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        _reject("invalid_label")
    protocol = _check_protocol(payload.get("protocol"))
    label = _check_label(payload.get("label"))
    base_url = _check_base_url(payload.get("base_url"))
    model = _check_model(payload.get("model"))
    secret = _check_key(payload.get("key"))
    connection_id = uuid.uuid4().hex
    record = {
        "id": connection_id,
        "label": label,
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "last4": _last4(secret),
        "verified": False,
        "last_outcome": None,
    }
    with _LOCK:
        _store_secret(connection_id, secret)
        try:
            connections = _load()
            connections.append(record)
            _write(connections)
        except Exception:
            _delete_secret(connection_id)
            raise
    return {"id": connection_id, "outcome": "saved"}


def _replace(record: dict[str, Any]) -> None:
    connections = [item for item in _load() if item.get("id") != record["id"]]
    connections.append(record)
    _write(connections)


def _probe(protocol: str, base_url: str, model: str) -> tuple[str, dict[str, Any]] | None:
    root = base_url.rstrip("/")
    if protocol == "openai-chat":
        return (
            f"{root}/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "stream": False,
            },
        )
    if protocol == "openai-responses":
        return (
            f"{root}/responses",
            {"model": model, "input": "Reply with OK.", "stream": False},
        )
    return None


def _http_post(
    url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
) -> httpx.Response:
    """POST one probe. stream=True keeps the status and drops the unread body."""
    with net.sync_client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        request = client.build_request("POST", url, headers=headers, json=payload)
        response = client.send(request, stream=True)
        try:
            status = int(response.status_code)
        finally:
            response.close()
    return httpx.Response(status)


_VERIFY_STATUS = {
    200: "verified",
    401: "unauthorized",
    403: "unauthorized",
    404: "not_found",
    429: "rate_limited",
    400: "request_rejected",
    422: "request_rejected",
}


def _log_verify(outcome: str, status: int | None) -> None:
    logging.getLogger(LOGGER_NAME).warning(
        "apikey_verify outcome=%s status=%s", outcome, status
    )


_DEMOTE_OUTCOMES = {"unauthorized", "not_found", "request_rejected"}


def _seal_verify(
    connection_id: str, *, verified: bool, outcome: str, status: int | None
) -> dict[str, Any]:
    with _LOCK:
        record = _find(connection_id)
        if record is not None:
            if outcome == "verified":
                kept = True
            elif outcome in _DEMOTE_OUTCOMES:
                kept = False
            else:
                kept = bool(record.get("verified", False))
            updated = dict(record)
            updated["verified"] = kept
            updated["last_outcome"] = outcome
            _replace(updated)
    _log_verify(outcome, status)
    if outcome == "verified":
        return {"outcome": "verified"}
    return {"outcome": outcome, "http_status": status}


def verify_connection(connection_id: str) -> dict[str, Any]:
    with _LOCK:
        record = _find(connection_id)
        if record is None:
            raise ApiKeyLookupError(connection_id)
        try:
            secret = _read_secret(connection_id)
        except (OSError, UnicodeError, ValueError):
            secret = ""
        base_url = str(record["base_url"])
        protocol = str(record.get("protocol") or "")
        model = str(record.get("model") or "")
    if not secret:
        return _seal_verify(
            connection_id, verified=False, outcome="unauthorized", status=None
        )
    target = _probe(protocol, base_url, model)
    if target is None:
        return _seal_verify(
            connection_id, verified=False, outcome="unexpected_response", status=None
        )
    url, payload = target
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }
    try:
        response = _http_post(url, headers, payload, 20)
    except (httpx.TimeoutException, httpx.TransportError, OSError, httpx.InvalidURL):
        return _seal_verify(
            connection_id, verified=False, outcome="unreachable", status=None
        )
    status = int(response.status_code)
    outcome = _VERIFY_STATUS.get(status, "unexpected_response")
    return _seal_verify(
        connection_id,
        verified=outcome == "verified",
        outcome=outcome,
        status=status,
    )


def delete_connection(connection_id: str) -> bool:
    with _LOCK:
        record = _find(connection_id)
        if record is None:
            return False
        _delete_secret(connection_id)
        _write([item for item in _load() if item.get("id") != connection_id])
        return True


class _PinnedModelClient:
    """Send the owner-typed model name while chat addresses the connection id."""

    def __init__(self, inner: Any, model: str) -> None:
        self._inner = inner
        self._model = model

    def create_conversation(self, model: str = "") -> Any:
        return self._inner.create_conversation(self._model)

    async def stream_generate(self, **kwargs: Any) -> Any:
        kwargs["model"] = self._model
        return await self._inner.stream_generate(**kwargs)


def build_agent_client(connection_id: str) -> Any | None:
    """Build the existing adapter for one verified connection, or None."""
    record = _find(connection_id)
    if record is None or not record.get("verified"):
        return None
    try:
        secret = _read_secret(connection_id)
    except (OSError, UnicodeError, ValueError):
        return None
    if not secret:
        return None
    base_url = str(record["base_url"]).rstrip("/")
    protocol = record.get("protocol")
    if protocol == "openai-responses":
        from .openai_responses_adapter import OpenAIResponsesApiClient

        inner: Any = OpenAIResponsesApiClient(base_url, secret)
    elif protocol == "openai-chat":
        from .openai_chat_adapter import OpenAIChatApiClient

        inner = OpenAIChatApiClient(base_url, secret, default_temperature=None)
    else:
        return None
    return _PinnedModelClient(inner, str(record["model"]))
