from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path

import pytest

from olga_companion.agent import approvals
from olga_companion.agent.tool_validation import ToolError
from olga_companion.case_compiler import render_case_spec
from olga_companion.case_publish_types import PublishTransactionSnapshot
from olga_companion.case_spec_validation import JsonObject
from case_spec_v2_support import PVT_TABLE_TEXT, with_v2_inputs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec() -> JsonObject:
    return with_v2_inputs({
        "version": "1",
        "nodes": [
            {"label": "SOURCE", "kind": "source", "pressure_pa": 2_000_000.0},
            {"label": "SINK", "kind": "sink", "pressure_pa": 1_000_000.0},
        ],
        "flowpaths": [{
            "label": "MAIN",
            "from": "SOURCE",
            "to": "SINK",
            "pipes": [{
                "label": "PIPE_A",
                "centerline_m": [[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
                "diameter_m": 0.1,
                "sections": 10,
            }],
        }],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 3600.0},
        "outputs": ["PT"],
    })


def test_server_approval_executes_exact_publish_and_rejects_token_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a reviewed transaction and a server-minted exact approval capability.
    from olga_companion.agent import case_publish_adapter

    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    source = workspace / "owner.genkey"
    compiled = private / "compiled.genkey"
    backup = private / "owner.backup.genkey"
    source.write_bytes(b"owner")
    compiled.write_bytes(render_case_spec(_spec()))
    (workspace / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    backup.write_bytes(source.read_bytes())
    transaction = PublishTransactionSnapshot(
        transaction_id="d" * 32,
        source=source,
        source_hash=_sha256(source),
        compiled=compiled,
        compiled_hash=_sha256(compiled),
        backup=backup,
        backup_hash=_sha256(backup),
        validation_clean=True,
        publishable=True,
        context_generation=9,
    )
    def load(_transaction_id: str) -> PublishTransactionSnapshot:
        return transaction
    args = {
        "transaction_id": transaction.transaction_id,
        "source_hash": transaction.source_hash,
        "compiled_hash": transaction.compiled_hash,
        "destination_rel": "published.genkey",
        "context_generation": 9,
    }

    @contextmanager
    def stable_context(_generation: int):
        yield workspace, 9

    monkeypatch.setattr(case_publish_adapter.workspace, "expected_context", stable_context)
    payload = case_publish_adapter.approval_payload(args, transaction_loader=load)
    token = approvals.mint("case_publish", payload, context_generation=9)["token"]
    approved = {**args, "approval_token": token, "idempotency_key": "t" * 32}

    # When: the approved action is called, then the same capability is reused.
    result = case_publish_adapter.execute(approved, transaction_loader=load)
    inode = (workspace / "published.genkey").stat().st_ino
    with pytest.raises(ToolError, match="unknown|used"):
        case_publish_adapter.execute(approved, transaction_loader=load)

    # Then: one file and its authoritative path-private receipt remain.
    assert result["state"] == "completed"
    assert result["destination_rel"] == "published.genkey"
    assert (workspace / "published.genkey").stat().st_ino == inode
    assert "approval_token" not in result
    assert "idempotency_key" not in result


def test_mismatched_publish_attempt_does_not_burn_exact_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an exact approval for one reviewed destination.
    from olga_companion.agent import case_publish_adapter

    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    compiled = private / "compiled.genkey"
    backup = private / "spec.json"
    compiled.write_bytes(render_case_spec(_spec()))
    (workspace / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    backup.write_bytes(b"spec")
    transaction = PublishTransactionSnapshot(
        transaction_id="e" * 32,
        source=None,
        source_hash=_sha256(backup),
        compiled=compiled,
        compiled_hash=_sha256(compiled),
        backup=backup,
        backup_hash=_sha256(backup),
        validation_clean=True,
        publishable=True,
        context_generation=2,
    )
    def load(_transaction_id: str) -> PublishTransactionSnapshot:
        return transaction
    args = {
        "transaction_id": transaction.transaction_id,
        "source_hash": transaction.source_hash,
        "compiled_hash": transaction.compiled_hash,
        "destination_rel": "exact.genkey",
        "context_generation": 2,
    }

    @contextmanager
    def stable_context(_generation: int):
        yield workspace, 2

    monkeypatch.setattr(case_publish_adapter.workspace, "expected_context", stable_context)
    payload = case_publish_adapter.approval_payload(args, transaction_loader=load)
    token = approvals.mint("case_publish", payload, context_generation=2)["token"]

    # When: a tampered destination is attempted before the exact action.
    with pytest.raises(ToolError, match="does not match"):
        case_publish_adapter.execute(
            {
                **args,
                "destination_rel": "tampered.genkey",
                "approval_token": token,
                "idempotency_key": "u" * 32,
            },
            transaction_loader=load,
        )
    result = case_publish_adapter.execute(
        {**args, "approval_token": token, "idempotency_key": "u" * 32},
        transaction_loader=load,
    )

    # Then: only the exact human-reviewed destination is created.
    assert result["state"] == "completed"
    assert (workspace / "exact.genkey").read_bytes() == compiled.read_bytes()
    assert not (workspace / "tampered.genkey").exists()


def test_adapter_loads_real_durable_casespec_transaction_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: transaction core persisted a validated source-free CaseSpec edit.
    from olga_companion.agent import case_publish_adapter
    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    (workspace / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(private / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    spec = _spec()
    plan = plan_case_edits(
        spec,
        [{"op": "set_outputs", "outputs": ["PT", "TM"]}],
        expected_hash=case_spec_hash(spec),
        workspace_root=workspace,
        context_generation=6,
    )
    # A failed plan is a TransactionFailure; surface its errors instead of an AttributeError.
    assert plan.publishable is True, getattr(plan, "errors", plan)
    args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": "built.genkey",
        "context_generation": 6,
    }

    @contextmanager
    def stable_context(_generation: int):
        yield workspace, 6

    monkeypatch.setattr(case_publish_adapter.workspace, "expected_context", stable_context)
    payload = case_publish_adapter.approval_payload(args)
    token = approvals.mint("case_publish", payload, context_generation=6)["token"]

    # When: a fresh adapter load executes the exact approved transaction.
    receipt = case_publish_adapter.execute(
        {**args, "approval_token": token, "idempotency_key": "w" * 32}
    )

    # Then: the stored compile is published and path-private receipt is returned.
    assert receipt["published_hash"] == plan.compiled_hash
    assert _sha256(workspace / "built.genkey") == plan.compiled_hash
    assert "source" not in receipt


def test_publish_refuses_a_destination_without_its_matching_pvt_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a clean reviewed plan whose table exists only at the workspace root.
    from olga_companion import case_publish
    from olga_companion.case_publish_types import PublishRefusedError, PublishRequest
    from olga_companion.case_transaction_store import load_transaction
    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    workspace = tmp_path / "workspace"
    (workspace / "sub").mkdir(parents=True)
    (workspace / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    spec = _spec()
    plan = plan_case_edits(
        spec, [{"op": "set_outputs", "outputs": ["PT", "TM"]}],
        expected_hash=case_spec_hash(spec), workspace_root=workspace, context_generation=4,
    )
    assert plan.publishable is True, getattr(plan, "errors", plan)
    transaction = load_transaction(plan.transaction_id)

    def request(destination: str) -> PublishRequest:
        return PublishRequest(
            transaction_id=plan.transaction_id, source_hash=plan.source_hash,
            compiled_hash=plan.compiled_hash, destination_rel=destination, context_generation=4,
            idempotency_key="k" * 32,
        )

    # When: publishing into a folder with no table, then with a different fluid label.
    with pytest.raises(PublishRefusedError) as missing:
        case_publish.publish_case(request("sub/built.genkey"), transaction, workspace, current_context_generation=4)
    (workspace / "sub" / "fluid.tab").write_text('PVTTABLE LABEL = "OTHER", PHASE = BOTH\n', encoding="utf-8")
    with pytest.raises(PublishRefusedError) as wrong:
        case_publish.publish_case(request("sub/built.genkey"), transaction, workspace, current_context_generation=4)

    # Then: nothing was written either time; a matching table lets the same plan publish.
    assert missing.value.code == wrong.value.code == "pvt_companion"
    assert not (workspace / "sub" / "built.genkey").exists()
    (workspace / "sub" / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    receipt = case_publish.publish_case(request("sub/built.genkey"), transaction, workspace, current_context_generation=4)
    assert receipt.published_hash == plan.compiled_hash


def test_approval_is_refused_up_front_when_the_table_is_not_beside_the_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.agent import case_publish_adapter
    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    workspace = tmp_path / "workspace"
    (workspace / "sub").mkdir(parents=True)
    (workspace / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    spec = _spec()
    plan = plan_case_edits(spec, [{"op": "set_outputs", "outputs": ["PT", "TM"]}],
                           expected_hash=case_spec_hash(spec), workspace_root=workspace, context_generation=4)
    assert plan.publishable is True

    @contextmanager
    def stable_context(_generation: int):
        yield workspace, 4

    monkeypatch.setattr(case_publish_adapter.workspace, "expected_context", stable_context)
    args = {"transaction_id": plan.transaction_id, "source_hash": plan.source_hash,
            "compiled_hash": plan.compiled_hash, "destination_rel": "sub/built.genkey", "context_generation": 4}

    # The human is never asked to approve a publish that cannot succeed.
    with pytest.raises(ToolError, match="pvt_companion"):
        case_publish_adapter.approval_payload(args)
    (workspace / "sub" / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    assert case_publish_adapter.approval_payload({**args}) is not None
