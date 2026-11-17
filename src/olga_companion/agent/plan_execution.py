"""Run one approved plan step by step under the plan's single, already-claimed approval."""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable
from typing import Any

from .. import genkey_static, workspace
from . import approvals, pending_approvals, plan_model, plan_progress, tools

_STEP_UNCERTAIN = "The step's outcome could not be confirmed. Inspect the workspace before retrying."
_MAX_ERROR = 400
_HEX64 = re.compile(r"[0-9a-f]{64}")
_PATH_SEPARATOR = re.compile(r"[\\/]")
# A unit such as kg/m3, J/kg/C or s2/m2 holds slashes without being a path. Only a chain of known
# unit atoms, standing alone, is exempt: a slash next to anything else still reads as a path.
_UNIT_ATOM = r"(?:kg|g|J|kJ|W|N|Ns|Pa|kPa|MPa|bar|s|m|C|K|mol|kmol|cP)\d?"
_UNIT_SLASHES = re.compile(rf"(?<![\w/\\.:~-]){_UNIT_ATOM}(?:/{_UNIT_ATOM})+(?![\w/\\]|\.\w)")
# A step's visible reason is a fixed sentence, or a short reason our own code wrote that
# carries no path. Anything else, such as an OS error text, falls back to these.
_FALLBACK = {
    "invalid_step": "The step was refused before it started, so nothing was changed.",
    "refused": "The step was refused before it started, so nothing was launched.",
    "failed": "The step failed after it started; its outcome is known, so nothing is left uncertain.",
    "check_failed": "The step could not be checked, so it was not started.",
}


class _Failure(Exception):
    """A step that stopped before it changed anything: a safe code and a safe sentence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PlanUncertainError(RuntimeError):
    """A step ended uncertain, so the plan is sealed and never resumed or retried."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        super().__init__("A plan step ended with an uncertain outcome.")
        self.steps = steps


def _reason(message: str, code: str) -> str:
    """A reason worth showing: short, one line and free of any path separator."""
    text = " ".join(message.split())[:_MAX_ERROR]
    return text if text and not _PATH_SEPARATOR.search(_UNIT_SLASHES.sub("", text)) else _FALLBACK[code]


def _now() -> float:
    return time.time()


def _key(pending_id: str, number: int) -> str:
    """Per-step idempotency key derived from the plan and the step index."""
    return hashlib.sha256(f"{pending_id}:{number}".encode()).hexdigest()[:32]


def _closed(kinds: list[str], error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "stopped",
        "error": error,
        "steps": [
            {"index": number, "kind": kind, "state": plan_progress.NOT_RUN}
            for number, kind in enumerate(kinds, start=1)
        ],
    }


def _require_published_bytes(origin: int, destination: str, expected: Any) -> None:
    """The run may only use the bytes the publish receipt describes."""
    if not isinstance(expected, str) or not _HEX64.fullmatch(expected):
        raise _Failure(
            "receipt_unverified",
            f"The save receipt of step {origin} has no file hash, so the saved case could not be "
            "verified and the run was not started.",
        )
    try:
        target = workspace.contained(destination)
        intact = (
            target.is_file()
            and not target.is_symlink()
            and genkey_static.file_sha256(target) == expected
        )
    except (OSError, workspace.WorkspaceError):
        intact = False
    if not intact:
        raise _Failure(
            "file_changed",
            "The saved case no longer matches what was published, so the run was not started.",
        )


def _bind(step: dict[str, Any], results: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Resolve a rule-bound run step: preview the published case now and require it clean."""
    args = dict(step["args"])
    origin = step.get("source_from_step")
    if origin is None:
        return args
    receipt = results.get(origin) or {}
    destination = receipt.get("destination_rel")
    if not isinstance(destination, str) or not destination:
        raise _Failure(
            "case_unknown", f"The case saved by step {origin} is not known, so the run was not started."
        )
    _require_published_bytes(origin, destination, receipt.get("published_hash"))
    timeout_s = args.get("timeout_s", 3600)
    preview = tools.dispatch("run_preview", {"source": destination, "timeout_s": timeout_s})
    validation = preview.get("validation")
    if not (isinstance(validation, dict) and validation.get("valid") is True):
        raise _Failure("not_clean", "The saved case did not validate cleanly, so the run was not started.")
    selection_id = str(preview.get("selection_id") or "")
    if not selection_id:
        raise _Failure("no_selection", "The run preview returned no selection, so the run was not started.")
    return {"source": destination, "timeout_s": timeout_s, "selection_id": selection_id}


def _check_draft(payload: dict[str, Any]) -> None:
    target = workspace.contained(payload["mfl_rel"])
    if not target.parent.is_dir():
        raise _Failure("draft_folder", "The selected draft folder does not exist, so nothing was written.")
    if os.path.lexists(target):
        raise _Failure(
            "draft_exists",
            "A file with that name already exists, so nothing was written. Choose a different file name.",
        )


def _publish_refusal_of(
    text: str, refusal: Callable[[str], dict[str, Any] | None]
) -> tuple[str, str] | None:
    """The fixed code and sentence for a known publish refusal; its raw detail is dropped."""
    refused = refusal(text)
    if refused is None:
        return None
    result = refused["result"]
    return str(result["code"]), str(result["error"])[:_MAX_ERROR]


def _run_step(
    pending_id: str,
    pending: pending_approvals.PendingApproval,
    number: int,
    step: dict[str, Any],
    results: dict[int, dict[str, Any]],
    refusal: Callable[[str], dict[str, Any] | None],
) -> tuple[str, dict[str, Any], str, str]:
    """Return the step's state, its result when done, and a safe message and code when not."""
    kind = step["kind"]
    try:
        args = _bind(step, results)
        payload = tools.approval_payload(kind, args)
        if kind == "fluids_draft_mfl":
            _check_draft(payload)
        token = approvals.mint(kind, payload, context_generation=pending.context_generation)["token"]
    except _Failure as failure:
        return plan_progress.FAILED, {}, failure.message, failure.code
    except (
        tools.ToolError,
        workspace.WorkspaceError,
        genkey_static.OlgaInputError,
        approvals.ApprovalError,
    ) as exc:
        return plan_progress.FAILED, {}, _reason(str(exc), "invalid_step"), "invalid_step"
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - nothing was dispatched yet
        return plan_progress.FAILED, {}, _FALLBACK["check_failed"], "check_failed"
    try:
        result = tools.dispatch(
            kind, {**args, "approval_token": token, "idempotency_key": _key(pending_id, number)}
        )
    except tools.ToolPreDispatchError as exc:
        return plan_progress.FAILED, {}, _reason(str(exc), "invalid_step"), "invalid_step"
    except tools.ToolRefusedError as exc:
        return plan_progress.FAILED, {}, _reason(str(exc), "refused"), "refused"
    except tools.ToolFailedError as exc:
        # The step ran far enough to leave a file behind (a table that failed its check): a
        # known failure with its own code, never worded as "refused before it started".
        return plan_progress.FAILED, {}, _reason(str(exc), "failed"), "table_rejected"
    except tools.ToolError as exc:
        known = _publish_refusal_of(str(exc), refusal)
        if known is not None:
            return plan_progress.FAILED, {}, known[1], known[0]
        return plan_progress.UNCERTAIN, {}, _STEP_UNCERTAIN, "uncertain"
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - an entered step seals uncertain
        return plan_progress.UNCERTAIN, {}, _STEP_UNCERTAIN, "uncertain"
    return plan_progress.DONE, result, "", ""


def run(
    pending_id: str,
    pending: pending_approvals.PendingApproval,
    *,
    refusal: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any]:
    """Run the registered steps in order; stop at the first failure; never add a step."""
    stored = plan_progress.load(pending_id)
    try:
        steps = plan_model.canonical_steps(pending.args.get("steps"))
        digest = plan_model.digest(
            pending.args, pending.session_id, pending.context_generation, pending.call_id
        )
    except plan_model.PlanError:
        return _closed([], "The approved plan could not be read; nothing was run.")
    kinds = [step["kind"] for step in steps]
    if stored is None or stored.get("digest") != digest:
        return _closed(kinds, "The approved plan changed after it was approved; nothing was run.")

    rows: list[dict[str, Any]] = [
        {"index": number, "kind": kind, "state": plan_progress.NOT_RUN}
        for number, kind in enumerate(kinds, start=1)
    ]
    results: dict[int, dict[str, Any]] = {}
    error = ""
    stopped_at: int | None = None
    for number, step in enumerate(steps, start=1):
        if _now() > float(stored["expires_epoch"]):
            error = f"The plan expired before step {number} started; nothing further was run."
            break
        plan_progress.mark(pending_id, number, plan_progress.RUNNING)
        state, output, message, code = _run_step(pending_id, pending, number, step, results, refusal)
        row = rows[number - 1]
        row["state"] = state
        if state == plan_progress.DONE:
            row["result"] = tools._cap(output)
            results[number] = output
            plan_progress.mark(pending_id, number, state, result=row["result"])
            continue
        row["error"] = message
        row["code"] = code
        plan_progress.mark(pending_id, number, state, error=message, code=code)
        stopped_at = number
        error = f"Step {number} ({step['kind']}) did not complete: {message}"
        break
    plan_progress.settle(pending_id)
    uncertain = any(row["state"] == plan_progress.UNCERTAIN for row in rows)
    done = all(row["state"] == plan_progress.DONE for row in rows)
    result: dict[str, Any] = {
        "ok": done,
        "state": "uncertain" if uncertain else "completed" if done else "stopped",
        "steps": rows,
    }
    if stopped_at is not None:
        result["stopped_at"] = stopped_at
    if error:
        result["error"] = error
    return result
