"""Clicks that never dispatch stay closed refusals, not an uncertain outcome."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from olga_companion import workspace
from olga_companion.agent import history, pending_approvals, session_token
from olga_companion.sidecar import app

EXECUTING = "이 승인은 이미 처리 중입니다."
INACTIVE = "이 승인 요청은 끝났습니다. 다시 요청하세요."
client = TestClient(app)


@pytest.fixture
def token():
    return session_token.boot_token()


@pytest.fixture(autouse=True)
def _clear() -> None:
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def _post(token: str, body: dict) -> dict:
    response = client.post(
        "/api/approvals/execute",
        json=body,
        headers={"X-Session-Token": token},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "failed"
    assert payload["resume_allowed"] is False
    assert "uncertain" not in json.dumps(payload)
    assert "Outcome uncertain" not in json.dumps(payload)
    return payload


def test_second_click_while_executing_is_a_closed_korean_refusal(token: str) -> None:
    session_id = history.new_session("already executing")
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": "case.genkey"},
        call_id="call-run",
        context_generation=generation,
        session_id=session_id,
    )
    pending_approvals.claim(
        pending_id,
        session_id=session_id,
        call_id="call-run",
        context_generation=generation,
    )

    body = _post(
        token,
        {
            "pending_id": pending_id,
            "session_id": session_id,
            "call_id": "call-run",
            "context_generation": generation,
        },
    )

    assert body["result"] == {
        "ok": False,
        "code": "approval_unavailable",
        "error": EXECUTING,
    }


def test_inactive_claim_is_a_closed_korean_refusal(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.agent import approval_execution

    def _inactive(**_kwargs):
        raise pending_approvals.ApprovalClaimInactiveError(
            "Pending approval claim is no longer active."
        )

    monkeypatch.setattr(approval_execution, "execute", _inactive)
    session_id = history.new_session("inactive claim")
    body = _post(
        token,
        {
            "pending_id": "d" * 32,
            "session_id": session_id,
            "call_id": "call-gone",
            "context_generation": workspace.context_generation(),
        },
    )

    assert body["result"] == {
        "ok": False,
        "code": "approval_unavailable",
        "error": INACTIVE,
    }


def test_inactive_claim_after_dispatch_stays_uncertain(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.agent import approval_execution

    def _ran(_kind: str, _args: dict) -> dict:
        pending_approvals.revoke_all()
        return {"ok": True}

    monkeypatch.setattr(approval_execution.tools, "approval_payload", lambda _kind, args: dict(args))
    monkeypatch.setattr(approval_execution.approvals, "mint", lambda *_args, **_kwargs: {"token": "tok"})
    monkeypatch.setattr(approval_execution.tools, "dispatch", _ran)
    session_id = history.new_session("dispatched then lost")
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": "case.genkey"},
        call_id="call-ran",
        context_generation=generation,
        session_id=session_id,
    )

    response = client.post(
        "/api/approvals/execute",
        json={
            "pending_id": pending_id,
            "session_id": session_id,
            "call_id": "call-ran",
            "context_generation": generation,
        },
        headers={"X-Session-Token": token},
    )
    payload = response.json()

    assert response.status_code == 409
    assert payload["state"] == "uncertain"
    assert payload.get("result", {}).get("code") != "approval_unavailable"
    assert INACTIVE not in json.dumps(payload)
