"""Approval and workspace adapter for the exact case publication action."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic import ValidationError

from .. import case_publish, case_transactions, workspace
from ..case_publish_journal import PublishJournalError
from ..case_publish_types import (
    PublishApprovalBinding,
    PublishReceipt,
    PublishRefusedError,
    PublishRequest,
    PublishTransactionSnapshot,
)
from ..case_spec_validation import JsonValue
from ..case_transaction_store import TransactionStoreError
from . import approvals
from .tool_validation import ToolError

TransactionLoader = Callable[[str], PublishTransactionSnapshot]
_DESTINATION_UNREADABLE = (
    "The save destination could not be checked. Choose another workspace folder and request again."
)


def _load_transaction(transaction_id: str) -> PublishTransactionSnapshot:
    stored = case_transactions.load_transaction(transaction_id)
    return PublishTransactionSnapshot(
        transaction_id=stored.transaction_id,
        source=stored.source,
        source_hash=stored.source_hash,
        compiled=stored.compiled,
        compiled_hash=stored.compiled_hash,
        backup=stored.backup,
        backup_hash=stored.backup_hash,
        validation_clean=stored.validation_clean,
        publishable=stored.publishable,
        context_generation=stored.context_generation,
    )


def _binding(args: Mapping[str, JsonValue]) -> PublishApprovalBinding:
    raw = {
        "transaction_id": args.get("transaction_id"),
        "source_hash": args.get("source_hash"),
        "compiled_hash": args.get("compiled_hash"),
        "destination_rel": args.get("destination_rel"),
        "context_generation": args.get("context_generation"),
    }
    try:
        return PublishApprovalBinding.model_validate(raw)
    except ValidationError as exc:
        raise ToolError(f"The pending case publication is malformed: {exc}") from exc


def _reviewed(
    args: Mapping[str, JsonValue],
    transaction_loader: TransactionLoader,
) -> tuple[PublishApprovalBinding, PublishTransactionSnapshot]:
    binding = _binding(args)
    try:
        transaction = transaction_loader(binding.transaction_id)
    except (OSError, TransactionStoreError) as exc:
        raise ToolError(str(exc)) from exc
    if (
        binding.source_hash != transaction.source_hash
        or binding.compiled_hash != transaction.compiled_hash
        or binding.context_generation != transaction.context_generation
    ):
        raise ToolError(
            "The pending case publication no longer matches its reviewed transaction."
        )
    if not transaction.publishable or not transaction.validation_clean:
        raise ToolError("The reviewed transaction is not publishable.")
    return binding, transaction


def _payload(binding: PublishApprovalBinding) -> dict[str, JsonValue]:
    return {
        "transaction_id": binding.transaction_id,
        "source_hash": binding.source_hash,
        "compiled_hash": binding.compiled_hash,
        "destination_rel": binding.destination_rel,
        "context_generation": binding.context_generation,
    }


def _result(receipt: PublishReceipt) -> dict[str, JsonValue]:
    return {
        "version": receipt.version,
        "receipt_id": receipt.receipt_id,
        "state": receipt.state,
        "transaction_id": receipt.transaction_id,
        "source_hash": receipt.source_hash,
        "compiled_hash": receipt.compiled_hash,
        "published_hash": receipt.published_hash,
        "backup_hash": receipt.backup_hash,
        "destination_rel": receipt.destination_rel,
        "context_generation": receipt.context_generation,
    }


def approval_payload(
    args: Mapping[str, JsonValue],
    *,
    transaction_loader: TransactionLoader = _load_transaction,
    planned_tables: Mapping[Path, str] | None = None,
) -> dict[str, JsonValue]:
    """Return the exact path-private payload the server binds to approval.

    ``planned_tables`` is passed only for a publish step that follows the plan step that
    creates its table; the step is checked strictly again when its turn comes.
    """
    binding, transaction = _reviewed(args, transaction_loader)
    # Ask the human only for a publish that can succeed: a table missing beside the
    # destination is knowable now, and refusing after approval would burn the approval.
    refusal: str | None = None
    with workspace.expected_context(binding.context_generation) as (root, _generation):
        destination = (root / binding.destination_rel).resolve()
        try:
            _ = case_publish.assert_publishable_destination(
                root, binding.destination_rel, transaction
            )
            case_publish.require_destination_companion(
                transaction.compiled.read_bytes(), destination, planned=planned_tables
            )
        except case_publish.PublishRefusedError as exc:
            # Not raised here: a frozen-dataclass error cannot cross the context manager.
            refusal = str(exc)
        except OSError:
            # An OS error text carries the full path; the person gets a fixed sentence.
            refusal = _DESTINATION_UNREADABLE
    if refusal is not None:
        raise ToolError(refusal)
    return _payload(binding)


def execute(
    args: Mapping[str, JsonValue],
    *,
    transaction_loader: TransactionLoader = _load_transaction,
) -> dict[str, JsonValue]:
    """Consume the server capability and publish the reviewed bytes exactly once."""
    token = args.get("approval_token")
    idempotency_key = args.get("idempotency_key")
    if not isinstance(token, str) or not isinstance(idempotency_key, str):
        raise ToolError(
            "case_publish requires a server-issued approval capability and idempotency key."
        )
    binding, transaction = _reviewed(args, transaction_loader)
    payload = _payload(binding)
    try:
        with workspace.expected_context(binding.context_generation) as (root, generation):
            approvals.consume(
                token,
                "case_publish",
                payload,
                context_generation=generation,
            )
            request = PublishRequest(
                transaction_id=binding.transaction_id,
                source_hash=binding.source_hash,
                compiled_hash=binding.compiled_hash,
                destination_rel=binding.destination_rel,
                context_generation=binding.context_generation,
                idempotency_key=idempotency_key,
            )
            receipt = case_publish.publish_case(
                request,
                transaction,
                root,
                current_context_generation=generation,
            )
            published = root / binding.destination_rel
            workspace.set_active_path(str(published))
    except approvals.ApprovalError as exc:
        raise ToolError(str(exc)) from exc
    except (PublishRefusedError, PublishJournalError, workspace.WorkspaceError) as exc:
        raise ToolError(str(exc)) from exc
    return _result(receipt)
