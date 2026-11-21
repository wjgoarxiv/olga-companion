"""A user's own edit of a workspace .genkey, with no assistant in the loop.

The edit runs the exact transaction an assistant edit runs: the same closed grammar, the same
compile and validator check, the same diff, the same single-use approval bound to the reviewed
transaction and workspace generation, and the same publish to a new file. Only who starts it
differs: the plan comes from the user's table and the approval is minted by the user's click,
as the companion-table copy already does.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import case_diff, case_edit_table, case_lint, case_preflight, case_transactions, run_stop_remedy, workspace
from .agent import approvals, case_publish_adapter, case_transaction_tools
from .agent.tool_validation import DEFAULT_PATH_BINDINGS, ToolError
from .case_publish_types import PublishOutcomeUncertainError
from .case_transaction_store import TransactionStoreError

router = APIRouter()

_IO_SENTENCE = "The case file could not be read or written. Nothing was saved."
_UNCERTAIN_SENTENCE = (
    "The edited copy may have been saved, but its receipt was not. "
    "Check the workspace for the new file before trying again."
)


def _facade() -> Any:
    from . import sidecar

    return sidecar


class CaseEditPlanRequest(BaseModel):
    source: str
    source_hash: str
    context_generation: int
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class CaseEditPublishRequest(BaseModel):
    transaction_id: str
    source_hash: str
    compiled_hash: str
    destination_rel: str
    context_generation: int
    approved: bool = False


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def _refused(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "refused", "message": message})


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise _refused(_IO_SENTENCE) from exc


def _source(value: str) -> tuple[Path, Path]:
    """The case file and the workspace root; a file outside the workspace is refused."""
    try:
        source = Path(_facade()._input_file(value, {".genkey"})).resolve()
    except workspace.WorkspaceError as exc:
        raise _refused(str(exc)) from exc
    root = workspace.context_identity()[0].resolve()
    if not source.is_relative_to(root):
        raise _refused("Only a case in the workspace can be edited here.")
    return source, root


def _require_current(source: Path, source_hash: str, generation: int) -> None:
    if workspace.context_generation() != generation:
        raise _conflict("stale_context", "The workspace changed since these values were read.")
    if _sha256(source) != source_hash:
        raise _conflict("stale_source", "The case file changed on disk since these values were read.")


@router.get("/api/case-edit/rows")
def api_case_edit_rows(rel: str) -> dict[str, Any]:
    source, root = _source(rel)
    generation = workspace.context_generation()
    try:
        rows = case_edit_table.editable_rows(source)
    except OSError as exc:
        raise _refused(_IO_SENTENCE) from exc
    coverage = case_lint.keyword_coverage(source, rows["rows"])
    return {**rows, "coverage": coverage, "source": source.relative_to(root).as_posix(), "context_generation": generation}


@router.get("/api/case-preflight")
def api_case_preflight(rel: str, x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    """A file checklist before a run; it reads the case and starts nothing."""
    _facade()._require_session_token(x_session_token)
    source, root = _source(rel)
    try:
        checklist = case_preflight.preflight(source)
    except OSError as exc:
        raise _refused(_IO_SENTENCE) from exc
    return {**checklist, "source": source.relative_to(root).as_posix(), "source_hash": _sha256(source)}


def _run_source(run_id: str) -> dict[str, Any]:
    """The case a finished run was started from, as its receipt recorded it."""
    from . import runner
    from .config import sandbox_root

    runner_record = runner.load_run_record(sandbox_root() / "runs" / runner.require_run_id(run_id))
    source = runner_record.get("source")
    return source if isinstance(source, dict) else {}


@router.get("/api/case-edit/remedy")
def api_case_edit_remedy(run_id: str) -> dict[str, Any]:
    """Which edit-table row a stopped run points at; nothing is written. The pointer is only
    for the exact case the run read: a case changed since then is refused."""
    sidecar = _facade()
    try:
        status = sidecar.run_status(run_id)
        source = _run_source(run_id)
    except sidecar.UnknownRunError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown run id: {run_id}") from exc
    except (sidecar.RunRecordError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="The run's receipt could not be read.") from exc
    root = workspace.context_identity()[0].resolve()
    path = Path(str(source.get("resolved_path") or "")).resolve()
    if not source.get("resolved_path") or not path.is_relative_to(root) or path.suffix.lower() != ".genkey":
        return {"rel": None, "row_id": None, "reason_key": "outside_workspace"}
    rel = path.relative_to(root).as_posix()
    try:
        if _sha256(path) != source.get("sha256"):
            return {"rel": rel, "row_id": None, "reason_key": "source_changed"}
        rows = case_edit_table.editable_rows(path)["rows"]
    except OSError:
        return {"rel": rel, "row_id": None, "reason_key": "source_changed"}
    coverage = case_lint.keyword_coverage(path, rows)
    return {"rel": rel, **run_stop_remedy.remedy_for(status.get("stop_reason"), rows, coverage)}


@router.get("/api/case-diff")
def api_case_diff(a: str, b: str) -> dict[str, Any]:
    """Keyword-level differences between two workspace cases; nothing is written."""
    before, root = _source(a)
    after, _ = _source(b)
    try:
        result = case_diff.diff_cases(before, after)
    except OSError as exc:
        raise _refused(_IO_SENTENCE) from exc
    return {**result, "a": before.relative_to(root).as_posix(), "b": after.relative_to(root).as_posix()}


@router.post("/api/case-edit/plan")
def api_case_edit_plan(
    request: CaseEditPlanRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _facade()._require_session_token(x_session_token)
    source, root = _source(request.source)
    _require_current(source, request.source_hash, request.context_generation)
    destination_rel = (source.parent / case_edit_table.edited_name(source)).relative_to(root).as_posix()
    try:
        with workspace.bound_to(request.context_generation):
            result = case_transaction_tools.edit_plan(
                {
                    "source": str(source),
                    "source_hash": request.source_hash,
                    "operations": request.operations,
                    "destination_rel": destination_rel,
                },
                DEFAULT_PATH_BINDINGS,
            )
    except workspace.StaleWorkspaceContextError as exc:
        raise _conflict("stale_context", str(exc)) from exc
    except ToolError as exc:
        message = str(exc)
        raise _refused(_IO_SENTENCE if "Errno" in message else message) from exc
    except OSError as exc:
        raise _refused(_IO_SENTENCE) from exc
    return {**result, "destination_rel": destination_rel}


def _table_transaction(request: CaseEditPublishRequest) -> Path:
    """The stored transaction must be a source edit whose copy lands beside its source, as the table plans."""
    try:
        stored = case_transactions.load_transaction(request.transaction_id)
    except (TransactionStoreError, OSError) as exc:
        raise _refused("This reviewed change is no longer available; review it again.") from exc
    root = workspace.context_identity()[0].resolve()
    if stored.source is None:
        raise _refused("Only a change reviewed in this table can be saved here.")
    source = Path(stored.source).resolve()
    destination = (root / request.destination_rel).resolve()
    if not source.is_relative_to(root) or not case_edit_table.is_edited_copy(source, destination):
        raise _refused("Only a change reviewed in this table can be saved here.")
    return destination


@router.post("/api/case-edit/publish")
def api_case_edit_publish(
    request: CaseEditPublishRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """The user's Approve click: mint the single-use approval for this exact reviewed edit and use it."""
    _facade()._require_session_token(x_session_token)
    if not request.approved:
        raise _refused("Saving an edited copy needs your approval.")
    destination = _table_transaction(request)
    if destination.is_file() and not destination.is_symlink() and _sha256(destination) == request.compiled_hash:
        # A retry after a save whose answer was lost: the reviewed bytes are already there.
        workspace.set_active_path(str(destination))
        return {"state": "completed", "published_hash": request.compiled_hash, "destination_rel": request.destination_rel}
    args: dict[str, Any] = {
        "transaction_id": request.transaction_id,
        "source_hash": request.source_hash,
        "compiled_hash": request.compiled_hash,
        "destination_rel": request.destination_rel,
        "context_generation": request.context_generation,
    }
    try:
        payload = case_publish_adapter.approval_payload(args)
        token = approvals.mint("case_publish", payload, context_generation=request.context_generation)["token"]
        receipt = case_publish_adapter.execute(
            {**args, "approval_token": token, "idempotency_key": request.transaction_id}
        )
    except workspace.StaleWorkspaceContextError as exc:
        raise _conflict("stale_context", str(exc)) from exc
    except PublishOutcomeUncertainError as exc:
        raise HTTPException(status_code=500, detail={"code": "uncertain", "message": _UNCERTAIN_SENTENCE}) from exc
    except (ToolError, approvals.ApprovalError) as exc:
        message = str(exc)
        if "stale_source" in message or "source changed" in message.casefold():
            raise _conflict("stale_source", "The case file changed on disk after the review; nothing was saved.") from exc
        raise _refused(_IO_SENTENCE if "Errno" in message else message) from exc
    except OSError as exc:
        raise _refused(_IO_SENTENCE) from exc
    return {**receipt, "destination_rel": request.destination_rel}
