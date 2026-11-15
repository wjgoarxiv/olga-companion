from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Installing an update stops the local backend and everything it supervises. Only a
# receipt that proves the run ended lets the update through; "running", "finalizing",
# "supervision_unknown" and "recovery_unknown" all lack that proof.
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "timed_out"})
# Unlike the history list, the gate must see every run directory or refuse to answer.
MAX_SCANNED_RUN_DIRECTORIES = 20_000
NO_END_STATES = frozenset({"recovery_unknown", "unreadable_receipt"})
UPDATE_LATCHED_MESSAGE = (
    "An application update is being installed, so no new run can start. "
    "Restart OLGA Companion and start the run again."
)


# Files that only exist once a process was started for the run (the first receipt is
# written before any of them), so finding one beside a missing run.json means the receipt
# was lost after a launch, not that nothing ever ran.
LAUNCH_TRACE_NAMES = frozenset(
    {"broker-request.json", "broker-status.json", "broker-cancel.json", "olga-explorer-broker.exe", "run.log"}
)
LAUNCH_TRACE_SUFFIXES = frozenset({".out", ".tpl", ".ppl"})


def _has_launch_trace(run_dir: Path) -> bool:
    with os.scandir(run_dir) as entries:
        return any(
            entry.name.lower() in LAUNCH_TRACE_NAMES
            or Path(entry.name).suffix.lower() in LAUNCH_TRACE_SUFFIXES
            for entry in entries
        )


def _unreadable(name: str) -> dict[str, str]:
    return {"run_id": name, "state": "unreadable_receipt"}


def scan_open_receipts(ctx: Any) -> list[dict[str, str]]:
    """Every persisted run whose end is not proven; raises OSError when the scan cannot finish."""
    runs_root = Path(ctx.sandbox_root()) / "runs"
    blocking: list[dict[str, str]] = []
    try:
        entries = os.scandir(runs_root)
    except FileNotFoundError:
        return blocking
    with entries:
        for inspected, entry in enumerate(entries, start=1):
            if inspected > MAX_SCANNED_RUN_DIRECTORIES:
                raise OSError("too many run directories to inspect")
            if entry.is_symlink():
                blocking.append(_unreadable(entry.name))
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            run_dir = Path(entry.path)
            try:
                record = ctx.load_run_record(run_dir)
            except FileNotFoundError:
                # Staging leftovers with no receipt never reached a launch; launch traces do.
                try:
                    traced = _has_launch_trace(run_dir)
                except OSError:
                    traced = True
                if traced:
                    blocking.append(_unreadable(entry.name))
                continue
            except (ctx.RunRecordError, OSError):
                blocking.append(_unreadable(entry.name))
                continue
            if record["phase"] == "terminal":
                continue
            try:
                state = str(ctx._status_from_receipt(record, run_dir)["state"])
            except Exception:  # noqa: BLE001 - an unreadable status is an unproven end
                blocking.append(_unreadable(entry.name))
                continue
            if state not in TERMINAL_STATES:
                blocking.append({"run_id": entry.name, "state": state})
    return blocking


def _message(blocking: list[dict[str, str]], starting: int) -> str:
    parts = []
    if starting:
        parts.append(f"{starting} run(s) are still starting")
    if blocking:
        names = ", ".join(f"{item['run_id']} ({item['state']})" for item in blocking[:3])
        extra = f" and {len(blocking) - 3} more" if len(blocking) > 3 else ""
        parts.append(f"run(s) still active or with unknown status: {names}{extra}")
    text = (
        "Installing the update stops the local backend and would end work in progress: "
        + "; ".join(parts)
        + ". Open Run, wait for them to finish or cancel them, then install again."
    )
    no_end = [item["run_id"] for item in blocking if item["state"] in NO_END_STATES]
    if no_end:
        text += (
            f" {', '.join(no_end[:3])} has no recorded end and cannot be cancelled from the app;"
            " the update stays blocked until that record is resolved."
        )
    return text


def _cancelled() -> dict[str, Any]:
    return {
        "safe": False,
        "confirmed": True,
        "blocking": [],
        "starting": 0,
        "message": "This update attempt was cancelled. Try installing again.",
    }


def _unconfirmed() -> dict[str, Any]:
    return {
        "safe": False,
        "confirmed": False,
        "blocking": [],
        "starting": 0,
        "message": (
            "Could not confirm that no run is active, so the update was not installed. "
            "Open Run to check on your runs, then try again."
        ),
    }


def begin_update(ctx: Any, owner: str) -> dict[str, Any]:
    # One prepare at a time: the latch is taken and possibly given back around a slow scan,
    # and a second caller must never read the first one's temporary latch as its own.
    with ctx._UPDATE_PREPARE_LOCK:
        return _begin_update_serialized(ctx, owner)


def _begin_update_serialized(ctx: Any, owner: str) -> dict[str, Any]:
    """Atomically decide whether the backend may be stopped and, if so, refuse new launches.

    The launch latch is taken first and the slow receipt scan runs behind it, so no run can
    start, exit and be missed between the scan and the final answer. A run that is already
    starting or alive answers at once, without closing launches for a scan.

    A positive answer is never withdrawn by time and never taken over: the native side may act
    on it at any moment. Only `release` with the same `owner`, sent when that side gives up or
    fails to stop the backend, reopens launching; another owner is refused while it is held.
    """
    with ctx._REGISTRY_LOCK:
        starting = ctx._STARTING_RUNS
        if owner in ctx._RELEASED_PREPARES:
            return _cancelled()
        was_latched = bool(ctx._UPDATE_LATCHED)
        if was_latched and ctx._UPDATE_LATCH_OWNER != owner:
            # Another attempt holds the latch and may still be about to stop the backend on
            # the strength of its own "safe". It is never taken over or released from here.
            return {
                "safe": False,
                "confirmed": True,
                "blocking": [],
                "starting": 0,
                "message": (
                    "Another update attempt already closed launching and may still be stopping "
                    "OLGA Companion. Restart OLGA Companion, then try again."
                ),
            }
        try:
            live = [
                {"run_id": run_id, "state": "running"}
                for run_id, state in ctx._RUNS.items()
                if state.popen.poll() is None
            ]
        except Exception:  # noqa: BLE001 - a run whose status cannot be read is not known idle
            return _unconfirmed()
        if starting or live:
            return {
                "safe": False,
                "confirmed": True,
                "blocking": live,
                "starting": starting,
                "message": _message(live, starting),
            }
        if not was_latched:
            ctx._UPDATE_LATCHED = True
            ctx._UPDATE_LATCH_OWNER = owner
    try:
        blocking = scan_open_receipts(ctx)
    except Exception:  # noqa: BLE001 - not being able to look is not "idle"
        if not was_latched:
            _reopen(ctx, owner)
        return _unconfirmed()
    if blocking:
        if not was_latched:
            _reopen(ctx, owner)
    else:
        with ctx._REGISTRY_LOCK:
            # Cancelled (its release arrived while this scanned) or reopened by someone else:
            # nobody will act on this answer, or launching is no longer closed behind it.
            if owner in ctx._RELEASED_PREPARES:
                return _cancelled()
            if not ctx._UPDATE_LATCHED or ctx._UPDATE_LATCH_OWNER != owner:
                return _unconfirmed()
    return {
        "safe": not blocking,
        "confirmed": True,
        "blocking": blocking,
        "starting": 0,
        "message": _message(blocking, 0) if blocking else "",
    }


def _reopen(ctx: Any, owner: str | None) -> bool:
    with ctx._REGISTRY_LOCK:
        if owner is not None and ctx._UPDATE_LATCH_OWNER != owner:
            return False
        released = bool(ctx._UPDATE_LATCHED)
        ctx._UPDATE_LATCHED = False
        ctx._UPDATE_LATCH_OWNER = None
        return released


def release(ctx: Any, owner: str | None = None) -> bool:
    """Reopen launching. With an `owner`, only the prepare that holds the latch may do it.

    A release is remembered, so a prepare of that attempt that is still queued or scanning
    can no longer close launching on an answer its native side has given up on.
    """
    if owner is not None:
        with ctx._REGISTRY_LOCK:
            ctx._RELEASED_PREPARES.append(owner)
    return _reopen(ctx, owner)


@contextmanager
def starting_run(ctx: Any) -> Iterator[None]:
    """Hold the gate shut for the whole of a launch, from before Popen to after registration."""
    with ctx._REGISTRY_LOCK:
        if ctx._UPDATE_LATCHED:
            raise ctx.OlgaInputError(UPDATE_LATCHED_MESSAGE)
        ctx._STARTING_RUNS += 1
    try:
        yield
    finally:
        with ctx._REGISTRY_LOCK:
            ctx._STARTING_RUNS -= 1
