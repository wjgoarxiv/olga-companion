"""Server-minted approval tokens for side-effectful agent actions.

Safety contract (docs/ARCHITECTURE.md §Safety contract 1): executing a run (and
any future OPC write) requires an `approval_token` that only the UI approval
route can mint — after a human clicks Approve on the server-rendered exact
command. Tokens are single-use, expire after TTL_SECONDS, and are digest-bound
to the exact (action_kind, payload) pair, so the agent can neither invent one
nor reuse or repurpose one it has seen in the transcript.

This module is deliberately NOT registered as an agent tool anywhere.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

TTL_SECONDS = 600


class ApprovalError(ValueError):
    """Approval token missing, unknown, already used, expired, or mismatched."""


_LOCK = threading.Lock()
_TOKENS: dict[str, dict[str, Any]] = {}


def payload_digest(action_kind: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{action_kind}\n{canonical}".encode("utf-8")).hexdigest()


def mint(
    action_kind: str,
    payload: dict[str, Any],
    *,
    context_generation: int | None = None,
) -> dict[str, Any]:
    """Mint a single-use token for exactly this action. UI-route-only caller."""
    if not action_kind or not isinstance(action_kind, str):
        raise ApprovalError("action_kind is required.")
    if not isinstance(payload, dict) or not payload:
        raise ApprovalError("payload must be a non-empty object describing the exact action.")
    if context_generation is not None and (
        not isinstance(context_generation, int)
        or isinstance(context_generation, bool)
        or context_generation < 0
    ):
        raise ApprovalError("context_generation must be a non-negative integer.")
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + TTL_SECONDS
    with _LOCK:
        _TOKENS[token] = {
            "digest": payload_digest(action_kind, payload),
            "expires_at": expires_at,
            "action_kind": action_kind,
            "context_generation": context_generation,
        }
    return {
        "token": token,
        "expires_at": expires_at,
        "action_kind": action_kind,
        "context_generation": context_generation,
    }


def consume(
    token: str,
    action_kind: str,
    payload: dict[str, Any],
    *,
    context_generation: int | None = None,
) -> None:
    """Validate and burn the token. Raises ApprovalError on any failure.

    A digest mismatch does NOT burn the token: the legitimate human-approved
    action must stay executable after a bad (possibly adversarial) attempt.
    """
    with _LOCK:
        entry = _TOKENS.get(token)
        if entry is None:
            raise ApprovalError("Approval token unknown or already used.")
        if time.time() > entry["expires_at"]:
            del _TOKENS[token]
            raise ApprovalError("Approval token expired; request approval again.")
        if entry["digest"] != payload_digest(action_kind, payload):
            raise ApprovalError(
                "Approval token does not match this exact action; request approval for it."
            )
        if context_generation is not None and entry.get("context_generation") != context_generation:
            raise ApprovalError(
                "Approval token does not match the current workspace context; request approval again."
            )
        del _TOKENS[token]


def revoke_all() -> int:
    """Revoke every outstanding approval after a workspace context change."""
    with revoke_all_barrier() as count:
        return count


@contextmanager
def revoke_all_barrier() -> Iterator[int]:
    """Revoke and prevent concurrent mint/consume until context commit completes."""
    with _LOCK:
        count = len(_TOKENS)
        _TOKENS.clear()
        yield count
