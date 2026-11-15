from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from olga_companion import config, genkey_static, runner, sweep_execution, workspace
from olga_companion.agent import approval_execution, pending_approvals


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("OLGA_APPROVAL_JOURNAL_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(config, "project_root", lambda: tmp_path)
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


@pytest.mark.parametrize(
    "action_kind,args,target",
    [
        (
            "genkey_save",
            {"save_rel": "approved.genkey", "topology": "simple_pipeline"},
            "genkey",
        ),
        ("run_cancel", {"run_id": "run-approved"}, "run"),
        ("sweep_cancel", {"sweep_id": "sweep-approved"}, "sweep"),
    ],
)
def test_model_side_effect_dispatch_uses_server_idempotency_exactly_once(
    action_kind: str,
    args: dict[str, Any],
    target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        genkey_static,
        "create_and_save",
        lambda *_args: calls.append("genkey") or {"saved": True},
    )
    monkeypatch.setattr(
        runner,
        "cancel_run",
        lambda _run_id: calls.append("run") or {"cancelled": True},
    )
    monkeypatch.setattr(
        sweep_execution,
        "cancel_sweep",
        lambda _sweep_id: calls.append("sweep") or {"cancelled": True},
    )
    session_id = "abc123abc123"
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind=action_kind,
        args={**args, "idempotency_key": "model-forged"},
        call_id=f"call-{target}",
        context_generation=generation,
        session_id=session_id,
    )
    payload = {
        "pending_id": pending_id,
        "session_id": session_id,
        "call_id": f"call-{target}",
        "context_generation": generation,
    }

    first = approval_execution.execute(**payload)
    replay = approval_execution.execute(**payload)

    assert first == replay
    assert first["state"] == "resume_pending"
    assert calls == [target]
