"""Server-authoritative reload contract for pending Chat approvals."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import sidecar, workspace
from olga_companion.agent import history, pending_approvals


@pytest.fixture
def isolated_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    pending_approvals.revoke_all()
    yield TestClient(sidecar.app)
    pending_approvals.revoke_all()


def test_reload_annotates_only_exact_live_pending_approval(
    isolated_api: TestClient,
) -> None:
    # Given: one server-live pending action and one persisted identity mismatch.
    session_id = history.new_session("approval reload")
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute", args={"selection_id": "selection-1"},
        call_id="call-1", context_generation=generation, session_id=session_id,
    )
    for call_id in ("call-1", "call-decoy"):
        history.append(
            session_id,
            {
                "record": "approval", "state": "pending", "pending_id": pending_id,
                "call_id": call_id, "workspace_generation": generation,
            },
        )

    # When: history reloads while server intent is live.
    active = isolated_api.get(f"/api/chat/session/{session_id}").json()["records"]
    approvals = [record for record in active if record.get("record") == "approval"]

    # Then: only the exact server-bound record is actionable.
    assert approvals[0]["actionable"] is True
    assert "actionable" not in approvals[1]

    # When: process-local intent is revoked, as after a sidecar restart.
    pending_approvals.revoke_all()
    restarted = isolated_api.get(f"/api/chat/session/{session_id}").json()["records"]

    # Then: durable orphan records never regain an approval action.
    assert all("actionable" not in record for record in restarted)
