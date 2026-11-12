"""T9c RED: every 409 from the approval execute path carries a machine-readable code.

Owner repro (2026-11-12): clicking "approve and write" showed the generic
chat error while the sidecar logged POST /api/approvals/execute status=409.
Expired/used approvals return 200 failure bodies, so a 409 is one of:
stale-generation click, context mismatch, dispatch-uncertain, or rejected.
The UI must be able to tell them apart instead of rendering generic text.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from olga_companion import workspace
from olga_companion.agent import history, pending_approvals, session_token
from olga_companion import sidecar


@pytest.fixture(autouse=True)
def _clear() -> None:
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _execute(api: TestClient, pending_id: str, session_id: str, generation: int):
    return api.post(
        "/api/approvals/execute",
        json={
            "pending_id": pending_id,
            "session_id": session_id,
            "call_id": "call-write",
            "context_generation": generation,
        },
        headers=_headers(),
    )


def test_stale_generation_click_is_a_coded_409(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = str(
        api.post("/api/chat/session", json={"title": ""}, headers=_headers()).json()[
            "session_id"
        ]
    )
    from olga_companion import config

    config.set_workspace_root(str(old_root))
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"destination_rel": "out.genkey"},
        call_id="call-write",
        context_generation=generation,
        session_id=session_id,
    )
    switched = workspace.switch_root(str(new_root))
    assert switched["generation"] == generation + 1

    response = _execute(api, pending_id, session_id, generation)

    assert response.status_code == 409
    assert response.json()["code"] == "approval_context_changed"


def test_same_folder_reselect_does_not_bump_generation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    root = tmp_path / "ws"
    root.mkdir()
    from olga_companion import config

    config.set_workspace_root(str(root))
    before = workspace.context_generation()

    result = workspace.switch_root(str(root))

    assert result["changed"] is False
    assert workspace.context_generation() == before


def test_session_mismatch_reports_identity_code_not_workspace_change(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = str(
        api.post("/api/chat/session", json={"title": ""}, headers=_headers()).json()[
            "session_id"
        ]
    )
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"destination_rel": "out.genkey"},
        call_id="call-write",
        context_generation=generation,
        session_id=session_id,
    )

    response = api.post(
        "/api/approvals/execute",
        json={
            "pending_id": pending_id,
            "session_id": "f" * 32,
            "call_id": "call-write",
            "context_generation": generation,
        },
        headers=_headers(),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "approval_identity_mismatch"


def test_generation_mismatch_with_live_pending_is_a_coded_409(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = str(
        api.post("/api/chat/session", json={"title": ""}, headers=_headers()).json()[
            "session_id"
        ]
    )
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"destination_rel": "out.genkey"},
        call_id="call-write",
        context_generation=generation,
        session_id=session_id,
    )

    response = _execute(api, pending_id, session_id, generation + 1)

    assert response.status_code == 409
    assert response.json()["code"] == "approval_context_changed"


def test_rejected_approval_execute_carries_rejected_code(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = str(
        api.post("/api/chat/session", json={"title": ""}, headers=_headers()).json()[
            "session_id"
        ]
    )
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"destination_rel": "out.genkey"},
        call_id="call-write",
        context_generation=generation,
        session_id=session_id,
    )
    pending_approvals.reject(
        pending_id,
        session_id=session_id,
        call_id="call-write",
        context_generation=generation,
    )

    response = _execute(api, pending_id, session_id, generation)

    assert response.status_code == 409
    assert response.json()["code"] == "approval_rejected"


def test_uncertain_dispatch_execute_carries_uncertain_code(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = str(
        api.post("/api/chat/session", json={"title": ""}, headers=_headers()).json()[
            "session_id"
        ]
    )
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"destination_rel": "out.genkey"},
        call_id="call-write",
        context_generation=generation,
        session_id=session_id,
    )
    pending_approvals.claim(
        pending_id,
        session_id=session_id,
        call_id="call-write",
        context_generation=generation,
    )
    # Simulate a restart between claim and completion: the journal replays the
    # in-flight claim as an uncertain terminal outcome.
    pending_approvals._PENDING.clear()
    pending_approvals._IN_FLIGHT.clear()
    pending_approvals._TERMINAL.clear()
    pending_approvals._restore()

    response = _execute(api, pending_id, session_id, generation)

    assert response.status_code == 409
    assert response.json()["code"] == "approval_dispatch_uncertain"
