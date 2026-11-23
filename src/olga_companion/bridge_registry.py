"""Connections from outside AI tools (0.1.20 P6): one secret and one chat session per product.

Connect issues a random secret that is written into that product's MCP entry; only its
SHA-256 is kept here. A bridge call names no product of its own: the product is whichever
issued secret matched, so a caller cannot label itself as another tool. Remove revokes.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from . import config

PRODUCTS: Final = {"claude-code": "Claude Code", "codex": "Codex", "gemini": "Gemini CLI"}
_LOCK = threading.Lock()


class BridgeRegistryError(ValueError):
    """Unknown product or unreadable registry."""


def _path() -> Path:
    return config.project_root() / "var" / "bridge-connections.json"


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"products": {}, "pending": {}}
    except (OSError, ValueError) as exc:
        raise BridgeRegistryError("The AI tool connection record could not be read.") from exc
    if not isinstance(data, dict):
        raise BridgeRegistryError("The AI tool connection record could not be read.")
    data.setdefault("products", {})
    data.setdefault("pending", {})
    return data


def _save(data: dict[str, Any]) -> None:
    config._atomic_write(_path(), json.dumps(data, sort_keys=True))


def _product(product: str) -> str:
    if product not in PRODUCTS:
        raise BridgeRegistryError(f"Unknown AI tool: {product!r}.")
    return product


def issue(product: str) -> str:
    """A fresh secret for `product`; any earlier one for it stops working."""
    with _LOCK:
        data = _load()
        secret = secrets.token_urlsafe(32)
        entry = data["products"].get(_product(product), {})
        data["products"][product] = {**entry, "secret_sha256": _digest(secret)}
        _save(data)
    return secret


def revoke(product: str) -> bool:
    with _LOCK:
        data = _load()
        entry = data["products"].get(_product(product))
        if not entry or "secret_sha256" not in entry:
            return False
        entry.pop("secret_sha256")
        _save(data)
    return True


def product_for(secret: str | None) -> str | None:
    """The product whose issued secret this is, else None."""
    if not secret or len(secret) > 256:
        return None
    digest = _digest(secret)
    try:
        data = _load()
    except BridgeRegistryError:
        return None
    for product, entry in data["products"].items():
        stored = entry.get("secret_sha256") if isinstance(entry, dict) else None
        if isinstance(stored, str) and secrets.compare_digest(stored, digest):
            return product
    return None


def connected(product: str) -> bool:
    try:
        entry = _load()["products"].get(_product(product))
    except BridgeRegistryError:
        return False
    return bool(isinstance(entry, dict) and entry.get("secret_sha256"))


def session_for(product: str, new_session: Any) -> str:
    """The app chat session that holds this product's approval cards (made on first use)."""
    with _LOCK:
        data = _load()
        entry = data["products"].setdefault(_product(product), {})
        session_id = entry.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = new_session(f"From {PRODUCTS[product]}")
            entry["session_id"] = session_id
            _save(data)
    return session_id


def set_connection(product: str, record: dict[str, Any] | None) -> None:
    """What Connect wrote, so Remove can restore the file exactly when it is untouched."""
    with _LOCK:
        data = _load()
        entry = data["products"].setdefault(_product(product), {})
        if record is None:
            entry.pop("connection", None)
        else:
            entry["connection"] = record
        _save(data)


def connection(product: str) -> dict[str, Any] | None:
    try:
        entry = _load()["products"].get(_product(product))
    except BridgeRegistryError:
        return None
    record = entry.get("connection") if isinstance(entry, dict) else None
    return record if isinstance(record, dict) else None


def forget_session(product: str) -> None:
    with _LOCK:
        data = _load()
        entry = data["products"].get(_product(product))
        if isinstance(entry, dict) and entry.pop("session_id", None) is not None:
            _save(data)


def is_bridge_session(session_id: str) -> bool:
    try:
        products = _load()["products"].values()
    except BridgeRegistryError:
        return False
    return any(isinstance(entry, dict) and entry.get("session_id") == session_id for entry in products)


@dataclass
class ChatTurn:
    """One in-app chat turn run by the local CLI. Lives only in this process's memory."""

    session_id: str
    generation: int
    selections: int | None
    locale: str
    expires: float
    halted: bool = False
    fill_active_case: bool = True


_CHAT_TURNS: dict[str, ChatTurn] = {}


def _now() -> float:
    return time.monotonic()


def issue_chat_turn(session_id: str, generation: int, locale: str, ttl: float, *, selections: int | None = None,
                    fill_active_case: bool = True) -> str:
    """A secret for one turn's MCP bridge. Only its hash is kept, and only in memory."""
    secret = secrets.token_urlsafe(32)
    with _LOCK:
        _CHAT_TURNS[_digest(secret)] = ChatTurn(session_id, generation, selections, locale, _now() + ttl,
                                                fill_active_case=fill_active_case)
    return secret


def chat_turn_for(secret: str | None) -> ChatTurn | None:
    if not secret or len(secret) > 256:
        return None
    digest = _digest(secret)
    with _LOCK:
        turn = _CHAT_TURNS.get(digest)
        if turn is not None and turn.expires < _now():
            _CHAT_TURNS.pop(digest, None)
            return None
        return turn


def halt_chat_turn(secret: str) -> None:
    with _LOCK:
        turn = _CHAT_TURNS.get(_digest(secret))
        if turn is not None:
            turn.halted = True


def revoke_chat_turn(secret: str) -> None:
    with _LOCK:
        _CHAT_TURNS.pop(_digest(secret), None)


def revoke_all_chat_turns() -> None:
    with _LOCK:
        _CHAT_TURNS.clear()


def record_pending(pending_id: str, record: dict[str, Any]) -> None:
    with _LOCK:
        data = _load()
        data["pending"][pending_id] = {**record, "ts": time.time()}
        # Keep the record small: the newest 256 bridge approvals, by time asked.
        if len(data["pending"]) > 256:
            oldest = sorted(data["pending"], key=lambda key: data["pending"][key].get("ts", 0))
            for stale in oldest[: len(data["pending"]) - 256]:
                data["pending"].pop(stale)
        _save(data)


def pending_record(pending_id: str, product: str) -> dict[str, Any] | None:
    """Only the product that asked may see its approval."""
    try:
        record = _load()["pending"].get(pending_id)
    except BridgeRegistryError:
        return None
    if not isinstance(record, dict) or record.get("product") != product:
        return None
    return record
