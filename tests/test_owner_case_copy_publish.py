"""Approved save of a reviewed copy for an owner GENKEY without CaseSpec provenance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from olga_companion import workspace
from olga_companion.agent import approvals, pending_approvals, tools
from olga_companion.case_spec_recovery import UnsupportedSourceError, recover_case_spec
from olga_companion.case_transaction_models import TransactionFailure
from olga_companion.case_transactions import plan_case_edits_from_source

_FIXTURE = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _owner_text(endtime: str = "900 s") -> str:
    text = _FIXTURE.read_text(encoding="utf-8")
    return text.replace("ENDTIME=24 h", f"ENDTIME={endtime}", 1)


@pytest.fixture(autouse=True)
def _clear_capabilities() -> None:
    approvals.revoke_all()
    pending_approvals.revoke_all()
    yield
    approvals.revoke_all()
    pending_approvals.revoke_all()


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endtime: str = "900 s") -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    source = root / "owner.genkey"
    source.write_text(_owner_text(endtime), encoding="utf-8")
    (root / "dummy_fluid.tab").write_text('PVTTABLE LABEL="FLUID-A"\n', encoding="utf-8")
    return root, source


def _plan(source: Path, root: Path, *, end_time_s: float = 60.0):
    return plan_case_edits_from_source(
        source,
        [{"op": "set_integration", "end_time_s": end_time_s}],
        expected_hash=_sha256(source),
        workspace_root=root,
        context_generation=workspace.context_generation(),
    )


def test_owner_endtime_plan_keeps_seconds_unit_and_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _workspace(tmp_path, monkeypatch)
    before = source.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()

    plan = _plan(source, root)

    assert _sha256(source) == before_hash
    assert source.read_bytes() == before
    assert plan.publishable is True
    assert plan.source_hash == before_hash
    assert b"ENDTIME=60 s" in plan.compiled_bytes
    assert b"ENDTIME=60 h" not in plan.compiled_bytes
    assert hashlib.sha256(plan.compiled_bytes).hexdigest() == plan.compiled_hash
    with pytest.raises(UnsupportedSourceError, match="provenance marker is absent"):
        recover_case_spec(source)


def test_missing_or_duplicate_endtime_and_closed_grammar_do_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _workspace(tmp_path, monkeypatch)
    missing = root / "missing.genkey"
    missing.write_text(_owner_text().replace("ENDTIME=900 s, ", "", 1), encoding="utf-8")
    duplicate = root / "duplicate.genkey"
    duplicate.write_text(
        _owner_text().replace(
            "INTEGRATION ENDTIME=900 s",
            "INTEGRATION ENDTIME=900 s\nINTEGRATION ENDTIME=800 s",
            1,
        ),
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in (source, missing, duplicate)}

    no_key = plan_case_edits_from_source(
        missing, [{"op": "set_integration", "end_time_s": 60.0}],
        expected_hash=_sha256(missing), workspace_root=root,
        context_generation=workspace.context_generation(),
    )
    two_keys = plan_case_edits_from_source(
        duplicate, [{"op": "set_integration", "end_time_s": 60.0}],
        expected_hash=_sha256(duplicate), workspace_root=root,
        context_generation=workspace.context_generation(),
    )
    foreign = plan_case_edits_from_source(
        source, [{"op": "set_magic", "end_time_s": 60.0}],
        expected_hash=_sha256(source), workspace_root=root,
        context_generation=workspace.context_generation(),
    )

    assert isinstance(no_key, TransactionFailure)
    assert isinstance(two_keys, TransactionFailure)
    assert isinstance(foreign, TransactionFailure)
    assert no_key.errors[0].code == two_keys.errors[0].code == "unknown_target"
    assert foreign.errors[0].code == "unsupported_operation"
    assert {path: path.read_bytes() for path in before} == before
    assert set(root.glob("*.genkey")) == {source, missing, duplicate}


def test_non_second_endtime_unit_is_not_converted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _workspace(tmp_path, monkeypatch, endtime="900 h")
    before = source.read_bytes()

    refused = _plan(source, root)

    assert isinstance(refused, TransactionFailure)
    assert refused.errors[0].code == "unit_unchanged"
    assert source.read_bytes() == before
    assert b"ENDTIME=60" not in source.read_bytes()


def test_publish_without_approval_creates_no_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _workspace(tmp_path, monkeypatch)
    before_hash = _sha256(source)
    plan = _plan(source, root)
    destination = root / "reviewed-copy.genkey"
    args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": destination.name,
        "context_generation": workspace.context_generation(),
    }
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args=args,
        call_id="call-owner-copy",
        context_generation=generation,
        session_id="session-owner-copy",
    )

    with pytest.raises(tools.ToolError):
        tools.dispatch("case_publish", args)

    stored = pending_approvals.claim(
        pending_id,
        session_id="session-owner-copy",
        call_id="call-owner-copy",
        context_generation=generation,
    )
    assert stored.action_kind == "case_publish"
    assert not destination.exists()
    assert _sha256(source) == before_hash


def test_approved_publish_writes_sibling_once_and_selects_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _workspace(tmp_path, monkeypatch)
    before_hash = _sha256(source)
    plan = _plan(source, root)
    assert plan.publishable is True
    args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": "reviewed-copy.genkey",
        "context_generation": workspace.context_generation(),
    }
    payload = tools.approval_payload("case_publish", args)
    token = approvals.mint(
        "case_publish", payload, context_generation=workspace.context_generation()
    )["token"]
    approved = {**args, "approval_token": token, "idempotency_key": "k" * 32}

    result = tools.dispatch("case_publish", approved)
    published = root / "reviewed-copy.genkey"

    assert result["published_hash"] == plan.compiled_hash
    assert published.read_bytes() == plan.compiled_bytes
    assert b"ENDTIME=60 s" in published.read_bytes()
    assert _sha256(source) == before_hash
    assert Path(workspace.active_path() or "") == published.resolve()
    review = tools.dispatch("genkey_review", {})
    consistency = tools.dispatch("fluids_consistency", {})
    assert Path(review["path"]) == published.resolve()
    assert Path(consistency["genkey"]) == published.resolve()
    assert consistency["source_mutated"] is False
    assert _sha256(source) == before_hash


@pytest.mark.parametrize(
    "destination",
    ["../escape.genkey", "/tmp/escape.genkey", "other/copy.genkey", "CON.genkey", "a:b.genkey", "-copy.genkey"],
)
def test_publish_refuses_escape_reserved_and_foreign_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    root, source = _workspace(tmp_path, monkeypatch)
    (root / "other").mkdir()
    before = source.read_bytes()
    plan = _plan(source, root)
    args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": destination,
        "context_generation": workspace.context_generation(),
    }

    with pytest.raises(tools.ToolError):
        tools.approval_payload("case_publish", args)

    assert source.read_bytes() == before
    assert not (root / "reviewed-copy.genkey").exists()
    assert not (root / "other" / "copy.genkey").exists()
    assert not (tmp_path / "escape.genkey").exists()


def test_publish_refuses_existing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _workspace(tmp_path, monkeypatch)
    existing = root / "reviewed-copy.genkey"
    existing.write_text("already\n", encoding="utf-8")
    before_source = source.read_bytes()
    before_existing = existing.read_bytes()
    plan = _plan(source, root)
    args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": existing.name,
        "context_generation": workspace.context_generation(),
    }

    with pytest.raises(tools.ToolError):
        tools.approval_payload("case_publish", args)

    assert source.read_bytes() == before_source
    assert existing.read_bytes() == before_existing


def test_stale_source_or_reviewed_bytes_publish_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _workspace(tmp_path, monkeypatch)
    plan = _plan(source, root)
    approved_hash = _sha256(source)
    source.write_bytes(source.read_bytes().replace(b"900", b"901", 1))
    args = {
        "transaction_id": plan.transaction_id,
        "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash,
        "destination_rel": "reviewed-copy.genkey",
        "context_generation": workspace.context_generation(),
    }
    payload = tools.approval_payload("case_publish", args)
    token = approvals.mint(
        "case_publish", payload, context_generation=workspace.context_generation()
    )["token"]

    with pytest.raises(tools.ToolError):
        tools.dispatch("case_publish", {**args, "approval_token": token, "idempotency_key": "k" * 32})

    assert not (root / "reviewed-copy.genkey").exists()
    assert _sha256(source) != approved_hash

    source.write_bytes(_owner_text().encode("utf-8"))
    fresh = _plan(source, root)
    compiled = tmp_path / "transactions" / fresh.transaction_id / "compiled.genkey"
    compiled.write_bytes(compiled.read_bytes().replace(b"ENDTIME=60 s", b"ENDTIME=61 s", 1))
    fresh_args = {
        "transaction_id": fresh.transaction_id,
        "source_hash": fresh.source_hash,
        "compiled_hash": fresh.compiled_hash,
        "destination_rel": "reviewed-copy.genkey",
        "context_generation": workspace.context_generation(),
    }
    with pytest.raises(tools.ToolError):
        tools.approval_payload("case_publish", fresh_args)
    assert not (root / "reviewed-copy.genkey").exists()
    assert _sha256(source) == fresh.source_hash
