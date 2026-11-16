"""An expired approval stays refused, and the card is told when it expires."""
from __future__ import annotations

import json
import time

import anyio
import pytest
from fastapi.testclient import TestClient

from olga_companion import workspace
from olga_companion.agent import (
    approval_event_persistence,
    history,
    pending_approvals,
    runtime,
    session_token,
)
from olga_companion.sidecar import app

SENTENCE = "승인 시간이 지났습니다. 다시 요청하세요."
client = TestClient(app)


@pytest.fixture
def token():
    return session_token.boot_token()


@pytest.fixture(autouse=True)
def _clear() -> None:
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def test_expired_pending_drops_its_epoch() -> None:
    session_id = history.new_session("epoch purge")
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": "case.genkey"},
        call_id="call-epoch",
        context_generation=1,
        session_id=session_id,
    )
    with pending_approvals._LOCK:
        _expires_at, record = pending_approvals._PENDING[pending_id]
        pending_approvals._PENDING[pending_id] = (time.monotonic() - 1, record)

    pending_approvals.register(
        action_kind="run_execute",
        args={"source": "other.genkey"},
        call_id="call-other",
        context_generation=1,
        session_id=session_id,
    )

    assert pending_id not in pending_approvals._EXPIRES_EPOCH


def test_registered_approval_keeps_the_ten_minute_deadline() -> None:
    before = time.time()
    pending_id = pending_approvals.register(
        action_kind="case_publish",
        args={"destination_rel": "x.genkey"},
        call_id="call-1",
        context_generation=0,
        session_id="a" * 16,
    )
    expires_at = pending_approvals.registered_expires_epoch(pending_id)
    after = time.time()

    assert pending_approvals.TTL_SECONDS == 600
    assert before + 600 <= expires_at <= after + 600
    with pytest.raises(
        pending_approvals.PendingApprovalError,
        match="Pending approval is unknown, expired, or already used",
    ):
        pending_approvals.claim(
            "b" * 32, session_id="a" * 16, call_id="call-1", context_generation=0
        )


def test_approval_event_carries_the_same_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = history.new_session("expiry")

    async def provider_events(*_args, **_kwargs):
        yield runtime.AgentEvent(
            "approval_required",
            {
                "name": "case_publish",
                "args": {"destination_rel": "x.genkey"},
                "call_id": "call-expiry",
                "context_generation": 0,
            },
        )

    monkeypatch.setattr(approval_event_persistence.runtime, "run_turn", provider_events)
    monkeypatch.setattr(
        approval_event_persistence.tools,
        "approval_display",
        lambda _name, _args, locale="ko": {},
    )
    before = time.time()
    events = anyio.run(
        approval_event_persistence.persist_runtime_events,
        object(),
        "model",
        object(),
        session_id,
        {"turn_id": "turn-1", "request_id": "request-1"},
        None,
    )
    after = time.time()
    streamed = events[0]["data"]
    persisted = next(
        record for record in history.read(session_id) if record.get("record") == "approval"
    )

    assert before + 600 <= streamed["expires_at"] <= after + 600
    assert persisted["expires_at"] == streamed["expires_at"]


def test_unknown_approval_click_is_unavailable_not_uncertain(token: str) -> None:
    session_id = history.new_session("expired click")
    response = client.post(
        "/api/approvals/execute",
        json={
            "pending_id": "c" * 32,
            "session_id": session_id,
            "call_id": "call-late",
            "context_generation": workspace.context_generation(),
        },
        headers={"X-Session-Token": token},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["state"] == "failed"
    assert body["resume_allowed"] is False
    assert body["result"] == {
        "ok": False,
        "code": "approval_unavailable",
        "error": SENTENCE,
    }
    assert "uncertain" not in json.dumps(body)
