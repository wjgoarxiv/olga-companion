"""Path-private agent adapter for reviewed CaseSpec edit transactions."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .. import case_publish, case_transactions, config, workspace
from ..case_transaction_models import TransactionFailure, TransactionPlan
from ..case_transaction_store import TransactionStoreError
from . import pipe_table_tools
from .tool_validation import MAX_RESULT_BYTES, PathBindings, ToolError


def _bounded(value: object, limit: int) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return rendered if len(rendered) <= limit else rendered[:limit]


def _snapshots(result: TransactionPlan | TransactionFailure) -> list[dict[str, Any]]:
    return [
        {
            "index": item.index,
            "hash": item.spec_hash,
            "previous_hash": item.previous_hash,
        }
        for item in result.snapshots
    ]


def _base(
    result: TransactionPlan | TransactionFailure,
    *,
    generation: int,
    source_kind: str,
) -> dict[str, Any]:
    return {
        "transaction_id": result.transaction_id,
        "source_hash": result.source_hash,
        "context_generation": generation,
        "source_kind": source_kind,
        "snapshots": _snapshots(result),
        "publishable": result.publishable,
        "source_mutated": False,
    }


def _success(
    result: TransactionPlan,
    *,
    generation: int,
    source_kind: str,
) -> dict[str, Any]:
    payload = {
        **_base(result, generation=generation, source_kind=source_kind),
        "transaction_hash": result.transaction_hash,
        "working_hash": result.working_hash,
        "compiled_hash": result.compiled_hash,
        "semantic_diff": [
            {
                "path": item.path[:256],
                "before": _bounded(item.before, 96),
                "after": _bounded(item.after, 96),
            }
            for item in result.semantic_diff
        ],
        "text_diff": [line[:160] for line in result.text_diff[:16]],
        "diff_truncated": len(result.text_diff) > 16
        or any(len(line) > 160 for line in result.text_diff[:16]),
        "backup": asdict(result.backup),
        "validation": {
            "clean": result.validation.clean,
            "parser_clean": result.validation.parser_clean,
            "validator_clean": result.validation.validator_clean,
            "diagnostics": [item[:128] for item in result.validation.diagnostics[:8]],
        },
        "rollback": asdict(result.rollback),
    }
    if len(json.dumps(payload, default=str)) > MAX_RESULT_BYTES:
        payload["text_diff"] = []
        payload["diff_truncated"] = True
    if len(json.dumps(payload, default=str)) > MAX_RESULT_BYTES:
        raise ToolError("The reviewed transaction receipt exceeds the safe result limit.")
    return payload


def _failure(
    result: TransactionFailure,
    *,
    generation: int,
    source_kind: str,
) -> dict[str, Any]:
    return {
        **_base(result, generation=generation, source_kind=source_kind),
        "failed_step": result.failed_step,
        "errors": [asdict(item) for item in result.errors],
    }


def _require_absent_destination(destination_rel: str) -> None:
    """Zero operations are a new case only. An existing path stays closed."""
    relative = Path(destination_rel)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.suffix.casefold() != ".genkey"
        or relative.name.startswith("-")
    ):
        raise workspace.WorkspaceError(
            "Destination must be a new workspace-relative .genkey file."
        )
    candidate = workspace.contained(destination_rel)
    if os.path.lexists(candidate):
        raise workspace.WorkspaceError(
            "case_edit_plan with zero operations requires a destination that does not exist yet."
        )


def edit_plan(args: dict[str, Any], paths: PathBindings) -> dict[str, Any]:
    """Plan ordered edits against one exact workspace or CaseSpec generation."""
    root, generation = workspace.context_identity()
    operations = args["operations"]
    if args.get("pending_table") and not config.native_tab_enabled():
        raise ToolError("pending_table is not available in this build.")
    source_kind = "source" if args.get("source") else "case_spec"
    draft_id = args.get("draft_id")
    draft = pipe_table_tools.load_draft(str(draft_id), generation) if draft_id else None
    try:
        destination_rel = args.get("destination_rel")
        if isinstance(destination_rel, str) and destination_rel:
            if draft is not None or (source_kind != "source" and not operations):
                _require_absent_destination(destination_rel)
            case_publish._destination(root, destination_rel)
        if source_kind == "source":
            source = paths.input_file(str(args["source"]), {".genkey"})
            result = case_transactions.plan_case_edits_from_source(
                source=workspace.contained(source),
                operations=operations,
                expected_hash=str(args["source_hash"]),
                workspace_root=root,
                context_generation=generation,
            )
        else:
            spec = draft.spec if draft is not None else args["spec"]
            result = case_transactions.plan_case_edits(
                spec,
                operations,
                expected_hash=(
                    case_transactions.case_spec_hash(spec) if draft is not None else str(args["spec_hash"])
                ),
                workspace_root=root,
                context_generation=generation,
                pending_companion=args.get("pending_table"),
            )
    except (
        OSError,
        ValidationError,
        TransactionStoreError,
        case_transactions.StaleSourceError,
        case_transactions.UnsupportedSourceError,
        case_transactions.UnsafeSourceError,
        workspace.WorkspaceError,
        case_publish.PublishRefusedError,
    ) as exc:
        raise ToolError(str(exc)) from exc
    if isinstance(result, TransactionFailure):
        return _failure(result, generation=generation, source_kind=source_kind)
    return _success(result, generation=generation, source_kind=source_kind)
