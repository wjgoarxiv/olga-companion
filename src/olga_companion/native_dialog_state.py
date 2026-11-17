"""Concurrent request and workspace-context lifecycle for native dialogs."""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import workspace
from .native_dialog_contracts import require_request_id

TerminateProcess = Callable[[Any], None]
CancelDialog = Callable[[str], dict[str, str]]


@dataclass  # noqa: RUF012  # noqa: MUTABLE_OK  # noqa: SLOTS_OK - lifecycle state
class DialogRequest:
    """Mutable process binding and cancellation state for one live request."""

    process: Any | None = None
    cancel_requested: bool = False


_REGISTRY_LOCK = threading.Lock()
_REGISTRY: dict[str, DialogRequest] = {}


@dataclass(eq=False)  # noqa: RUF012  # noqa: MUTABLE_OK  # noqa: SLOTS_OK - lease state
class ContextDialogLease:
    """Mutable identity token for the one context dialog allowed to apply."""

    request_id: str
    context_generation: int
    context_root: Path
    superseded: bool = False
    cancel_requested: bool = False
    committed: bool = False


_CONTEXT_DIALOG_LOCK = threading.Lock()
_CURRENT_CONTEXT_DIALOG: ContextDialogLease | None = None


def begin_context_dialog(
    request_id: str,
    context_generation: int,
    cancel_dialog: CancelDialog,
) -> ContextDialogLease:
    """Install a newer workspace/open-case request and supersede the prior exact lease."""
    require_request_id(request_id)
    global _CURRENT_CONTEXT_DIALOG
    with _CONTEXT_DIALOG_LOCK:
        with workspace.expected_context(context_generation) as identity:
            lease = ContextDialogLease(request_id, context_generation, identity[0])
            previous = _CURRENT_CONTEXT_DIALOG
            if previous is not None:
                previous.superseded = True
            _CURRENT_CONTEXT_DIALOG = lease
    if previous is not None:
        try:
            cancel_dialog(previous.request_id)
        except BaseException:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - restore coordinator
            finish_context_dialog(lease)
            raise
    return lease


def finish_context_dialog(lease: ContextDialogLease) -> None:
    global _CURRENT_CONTEXT_DIALOG
    with _CONTEXT_DIALOG_LOCK:
        if _CURRENT_CONTEXT_DIALOG is lease:
            _CURRENT_CONTEXT_DIALOG = None


def cancel_context_dialog(request_id: str) -> bool:
    """Mark only the exact current context request cancelled; never affect its successor."""
    require_request_id(request_id)
    with _CONTEXT_DIALOG_LOCK:
        lease = _CURRENT_CONTEXT_DIALOG
        if lease is None or lease.request_id != request_id or lease.committed:
            return False
        lease.cancel_requested = True
        return True


def context_dialog_result(
    lease: ContextDialogLease,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Return an honest non-mutating result for a cancelled or superseded lease."""
    with _CONTEXT_DIALOG_LOCK:
        if lease.superseded or _CURRENT_CONTEXT_DIALOG is not lease:
            return {"status": "superseded", "request_id": lease.request_id}
        if lease.cancel_requested:
            return {"status": "cancelled", "request_id": lease.request_id}
        return result


def apply_context_dialog(
    lease: ContextDialogLease,
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Apply a selection only while this exact lease and workspace generation are current."""
    with _CONTEXT_DIALOG_LOCK:
        if lease.superseded or _CURRENT_CONTEXT_DIALOG is not lease:
            return {"status": "superseded", "request_id": lease.request_id}
        if lease.cancel_requested:
            return {"status": "cancelled", "request_id": lease.request_id}
        with workspace.expected_context(lease.context_generation) as identity:
            if identity[0] != lease.context_root:
                raise workspace.StaleWorkspaceContextError(
                    "Workspace context changed; start the native dialog again."
                )
            result = action()
            lease.committed = True
            return result


def register_dialog(
    request_id: str,
    context_lease: ContextDialogLease | None,
    request: DialogRequest,
) -> dict[str, Any] | None:
    """Atomically validate a context lease and publish its process request slot."""
    with _CONTEXT_DIALOG_LOCK:
        if context_lease is not None:
            if (
                context_lease.superseded
                or _CURRENT_CONTEXT_DIALOG is not context_lease
            ):
                return {"status": "superseded", "request_id": request_id}
            if context_lease.cancel_requested:
                return {"status": "cancelled", "request_id": request_id}
        with _REGISTRY_LOCK:
            if request_id in _REGISTRY:
                return {"status": "unavailable", "reason": "duplicate request_id"}
            _REGISTRY[request_id] = request
    return None


def bind_process(request: DialogRequest, process: Any) -> bool:
    """Bind the launched process and return whether cancellation won the spawn race."""
    with _REGISTRY_LOCK:
        request.process = process
        return request.cancel_requested


def request_cancelled(request: DialogRequest) -> bool:
    with _REGISTRY_LOCK:
        return request.cancel_requested


def unregister_dialog(request_id: str, request: DialogRequest) -> None:
    with _REGISTRY_LOCK:
        if _REGISTRY.get(request_id) is request:
            del _REGISTRY[request_id]


def cancel_dialog(
    request_id: str,
    terminate_reap: TerminateProcess,
) -> dict[str, str]:
    require_request_id(request_id)
    with _REGISTRY_LOCK:
        request = _REGISTRY.get(request_id)
        if request is None:
            return {"status": "unavailable", "reason": "request_id is not active"}
        request.cancel_requested = True
        process = request.process
        del _REGISTRY[request_id]
    if process is not None:
        terminate_reap(process)
    return {"status": "cancelled", "request_id": request_id}


def active_request_ids() -> list[str]:
    with _REGISTRY_LOCK:
        return sorted(_REGISTRY)


def cancel_all(terminate_reap: TerminateProcess) -> None:
    global _CURRENT_CONTEXT_DIALOG
    with _CONTEXT_DIALOG_LOCK:
        current = _CURRENT_CONTEXT_DIALOG
        if current is not None:
            current.cancel_requested = True
        _CURRENT_CONTEXT_DIALOG = None
    with _REGISTRY_LOCK:
        requests = list(_REGISTRY.values())
        for request in requests:
            request.cancel_requested = True
        _REGISTRY.clear()
    for request in requests:
        if request.process is not None:
            terminate_reap(request.process)
