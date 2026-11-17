"""Redaction and size policy for persisted Chat evidence."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Final, TypeAlias, assert_never

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

MAX_STRING_CHARS: Final = 16_384
MAX_LIST_ITEMS: Final = 128
MAX_MAPPING_ITEMS: Final = 128
MAX_DEPTH: Final = 12
MAX_RECORD_BYTES: Final = 131_072

_CREDENTIAL_KEYS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "password",
        "refresh_token",
        "secret",
        "session_token",
        "token",
    }
)
_CREDENTIAL_COMPACT: Final = frozenset(
    {
        "accesstoken",
        "accesskey",
        "apikey",
        "authorization",
        "awsaccesskeyid",
        "awssecretaccesskey",
        "clientsecret",
        "cookie",
        "credentials",
        "password",
        "privatekey",
        "refreshtoken",
        "secret",
        "sessiontoken",
        "token",
        "xapikey",
    }
)
_ENVELOPE_KEYS: Final = (
    "record",
    "type",
    "turn_id",
    "request_id",
    "pending_id",
    "call_id",
    "artifact_id",
    "name",
    "provider",
    "model",
    "workspace_generation",
    "workspace_root",
    "source_identity",
    "source_hash",
    "state",
    "lifecycle",
)
_PRIVATE_PATH_MARKERS: Final = (
    "/.aws/",
    "/.azure/",
    "/.codex/",
    "/.ssh/",
    "/gcloud/",
    "/auth.json",
    "/credentials",
    "/id_ed25519",
    "/id_rsa",
)
_URL_USERINFO = re.compile(r"[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@", re.I)
_ABSOLUTE_PATH = re.compile(r"^(?:/|[a-z]:[\\/]|\\\\|//)", re.I)
_MAX_COMPACT_CALL_BYTES: Final = 768
_MAX_IDENTITY_CHARS: Final = 256
_MAX_SIGNATURE_BYTES: Final = 4_096


class CredentialMaterialError(ValueError):
    """A top-level persisted record attempted to carry a credential."""


def is_credential_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    compact = re.sub(r"[^a-z0-9]", "", key.casefold())
    return bool(
        normalized in _CREDENTIAL_KEYS
        or compact in _CREDENTIAL_COMPACT
        or compact.endswith(
            ("accesskey", "apikey", "password", "privatekey", "secret", "token")
        )
    )


def opaque_path_identity(value: str) -> str:
    """Return a stable one-way identity without exposing an absolute path."""
    return f"path-sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def sanitize_record(record: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Drop nested credentials and bound evidence without changing small values."""
    if any(is_credential_key(key) for key in record):
        raise CredentialMaterialError(
            "Refusing to persist a record containing credential material."
        )
    sanitized = _sanitize_mapping(record, depth=0)
    encoded = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= MAX_RECORD_BYTES:
        return sanitized
    envelope = {
        key: sanitized[key] for key in _ENVELOPE_KEYS if key in sanitized
    }
    fallback: dict[str, JsonValue] = {
        **envelope,
        "record": str(envelope.get("record", "event")),
        "truncated": True,
        "payload_hash": f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}",
        "summary": "Persisted evidence exceeded the bounded record size.",
    }
    if sanitized.get("record") == "assistant":
        _retain_assistant_replay(sanitized, fallback)
    if _encoded_size(fallback) > MAX_RECORD_BYTES:
        raise CredentialMaterialError(
            "Oversized assistant replay identity cannot be persisted safely."
        )
    return fallback


def sanitize_tool_result(result: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Canonicalize tool evidence before any terminal receipt can retain it."""
    normalized = json.loads(json.dumps(result, default=str))
    sanitized = _sanitize_mapping(normalized, depth=0)
    if _encoded_size(sanitized) <= MAX_RECORD_BYTES:
        return sanitized
    return {
        "truncated": True,
        "payload_hash": f"sha256:{_digest(sanitized)}",
        "summary": "Tool result exceeded the bounded evidence size.",
    }


def _sanitize_mapping(
    value: Mapping[str, JsonValue], *, depth: int
) -> dict[str, JsonValue]:
    if depth >= MAX_DEPTH:
        return {"truncated": True}
    output: dict[str, JsonValue] = {}
    for key, item in list(value.items())[:MAX_MAPPING_ITEMS]:
        if is_credential_key(key):
            continue
        output[str(key)] = _sanitize_value(item, key=key, depth=depth + 1)
    return output


def _sanitize_value(value: JsonValue, *, key: str, depth: int) -> JsonValue:
    if depth >= MAX_DEPTH:
        return "[truncated: depth limit]"
    match value:
        case None | bool() | int() | float():
            return value
        case str() if key.casefold().replace("-", "_") == "raw_arguments":
            return _sanitize_raw_arguments(value, depth=depth)
        case str():
            return _sanitize_string(value, key=key)
        case dict():
            return _sanitize_mapping(value, depth=depth)
        case list():
            return [
                _sanitize_value(item, key=key, depth=depth + 1)
                for item in value[:MAX_LIST_ITEMS]
            ]
        case unreachable:
            assert_never(unreachable)


def _sanitize_raw_arguments(value: str, *, depth: int) -> str:
    """Canonicalize structured provider arguments without retaining secrets."""
    if not value:
        return ""
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        decoded = None
    if not isinstance(decoded, dict):
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"json-sha256:{digest}"
    sanitized = _sanitize_mapping(decoded, depth=depth)
    return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))


def _retain_assistant_replay(
    sanitized: Mapping[str, JsonValue], fallback: dict[str, JsonValue]
) -> None:
    calls = sanitized.get("tool_calls")
    if not isinstance(calls, list):
        return
    compact_calls: list[JsonValue] = []
    replay_blocked = False
    for value in calls:
        if not isinstance(value, dict):
            replay_blocked = True
            continue
        identity: dict[str, JsonValue] = {}
        for key in ("name", "call_id", "item_id"):
            item = str(value.get(key, ""))
            if len(item) > _MAX_IDENTITY_CHARS:
                item = f"sha256:{hashlib.sha256(item.encode()).hexdigest()}"
                replay_blocked = True
            identity[key] = item
        candidate = {
            **identity,
            "args": value.get("args", {}),
            "raw_arguments": value.get("raw_arguments", ""),
        }
        if _encoded_size(candidate) <= _MAX_COMPACT_CALL_BYTES:
            compact_calls.append(candidate)
        else:
            replay_blocked = True
            compact_calls.append(
                {
                    **identity,
                    "replay_blocked": True,
                    "payload_hash": f"sha256:{_digest(value)}",
                }
            )
    fallback["text"] = sanitized.get("text", "")
    fallback["tool_calls"] = compact_calls
    signature = sanitized.get("thought_signature")
    if signature is not None:
        if _encoded_size(signature) <= _MAX_SIGNATURE_BYTES:
            fallback["thought_signature"] = signature
        else:
            fallback["thought_signature_identity"] = f"sha256:{_digest(signature)}"
            replay_blocked = True
    if replay_blocked:
        fallback["replay_blocked"] = True
        fallback["replay_block_reason"] = "oversized assistant evidence"


def _digest(value: JsonValue) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encoded_size(value: JsonValue | Mapping[str, JsonValue]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _sanitize_string(value: str, *, key: str) -> str:
    bounded = value[:MAX_STRING_CHARS]
    if bounded.startswith("path-sha256:"):
        return bounded
    if key.casefold().replace("-", "_") == "workspace_root":
        if bounded.startswith("path-sha256:"):
            return bounded
        return opaque_path_identity(bounded)
    if _URL_USERINFO.search(bounded):
        digest = hashlib.sha256(bounded.encode("utf-8")).hexdigest()
        return f"url-sha256:{digest}"
    if _ABSOLUTE_PATH.search(bounded):
        return opaque_path_identity(bounded)
    normalized = bounded.replace("\\", "/").casefold()
    if any(marker in normalized for marker in _PRIVATE_PATH_MARKERS):
        return opaque_path_identity(bounded)
    return bounded
