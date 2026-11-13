from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from olga_companion import workspace
from olga_companion.agent import approvals, pending_approvals, tools
from olga_companion.case_transactions import case_spec_hash, plan_case_edits
from olga_companion.case_spec_validation import JsonObject
from case_spec_v2_support import PVT_TABLE_TEXT, with_v2_inputs


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


@pytest.fixture(autouse=True)
def _clear_capabilities() -> None:
    approvals.revoke_all()
    pending_approvals.revoke_all()
    yield
    approvals.revoke_all()
    pending_approvals.revoke_all()


def test_registered_case_publish_dispatches_exact_transaction_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real durable transaction in the active workspace generation.
    workspace_root = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace_root.mkdir()
    private.mkdir()
    (workspace_root / "fluid.tab").write_text(PVT_TABLE_TEXT, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(private / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    spec = _spec()
    plan = plan_case_edits(
        spec,
        [{"op": "set_integration", "end_time_s": 7200.0}],
        expected_hash=case_spec_hash(spec),
        workspace_root=workspace_root,
        context_generation=workspace.context_generation(),
    )
    # A failed plan is a TransactionFailure; surface its errors instead of an AttributeError.
    assert plan.publishable is True, getattr(plan, "errors", plan)
    args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": "chat-built.genkey",
        "context_generation": workspace.context_generation(),
    }
    payload = tools.approval_payload("case_publish", args)
    token = approvals.mint(
        "case_publish",
        payload,
        context_generation=workspace.context_generation(),
    )["token"]
    approved = {**args, "approval_token": token, "idempotency_key": "x" * 32}

    # When: the registered side-effect handler receives the server capability twice.
    result = tools.dispatch("case_publish", approved)
    inode = (workspace_root / "chat-built.genkey").stat().st_ino
    with pytest.raises(tools.ToolError, match="unknown|used"):
        tools.dispatch("case_publish", approved)

    # Then: the exact compiled bytes and path-private receipt remain once.
    assert result["published_hash"] == plan.compiled_hash
    assert hashlib.sha256((workspace_root / "chat-built.genkey").read_bytes()).hexdigest() == plan.compiled_hash
    assert (workspace_root / "chat-built.genkey").stat().st_ino == inode


def test_rejected_case_publish_is_terminal_and_inert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a pending case publication that the human has not approved.
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={
            "transaction_id": "a" * 32,
            "source_hash": "b" * 64,
            "compiled_hash": "c" * 64,
            "destination_rel": "rejected.genkey",
            "context_generation": generation,
        },
        call_id="call-reject",
        context_generation=generation,
        session_id="session-reject",
    )

    # When: the user rejects it at the server state machine.
    rejected = pending_approvals.reject(
        pending_id,
        session_id="session-reject",
        call_id="call-reject",
        context_generation=generation,
    )

    # Then: no destination or action receipt is created.
    assert rejected.approval.action_kind == "case_publish"
    assert not (workspace_root / "rejected.genkey").exists()
    assert not (tmp_path / "journal").exists()
