from __future__ import annotations

import pytest

from olga_companion.agent import pending_approvals


@pytest.fixture(autouse=True)
def _clear_pending() -> None:
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def _register() -> str:
    return pending_approvals.register(
        action_kind="run_execute",
        args={"source": "/workspace/case.genkey", "selection_id": "selection-1"},
        call_id="call-1",
        context_generation=7,
        session_id="abc123abc123",
    )


def _claim(
    pending_id: str,
    *,
    call_id: str = "call-1",
    session_id: str = "abc123abc123",
) -> pending_approvals.PendingApproval:
    return pending_approvals.claim(
        pending_id,
        session_id=session_id,
        call_id=call_id,
        context_generation=7,
    )


def test_pending_approval_is_exact_bound_and_one_shot() -> None:
    pending_id = _register()

    record = pending_approvals.claim(
        pending_id,
        session_id="abc123abc123",
        call_id="call-1",
        context_generation=7,
    )

    assert record.action_kind == "run_execute"
    assert record.args["selection_id"] == "selection-1"
    with pytest.raises(pending_approvals.PendingApprovalError, match="unknown|used|executing"):
        pending_approvals.claim(
            pending_id,
            session_id="abc123abc123",
            call_id="call-1",
            context_generation=7,
        )


@pytest.mark.parametrize(
    "field,value",
    [("session_id", "def456def456"), ("call_id", "call-2"), ("context_generation", 8)],
)
def test_mismatch_does_not_burn_legitimate_pending_approval(field: str, value: str | int) -> None:
    pending_id = _register()
    claim = {
        "session_id": "abc123abc123",
        "call_id": "call-1",
        "context_generation": 7,
    }
    claim[field] = value

    with pytest.raises(pending_approvals.PendingApprovalError, match="does not match"):
        pending_approvals.claim(pending_id, **claim)

    assert pending_approvals.claim(
        pending_id,
        session_id="abc123abc123",
        call_id="call-1",
        context_generation=7,
    ).call_id == "call-1"


def test_pending_approval_refuses_preinjected_capability() -> None:
    with pytest.raises(pending_approvals.PendingApprovalError, match="must not contain"):
        pending_approvals.register(
            action_kind="run_execute",
            args={"selection_id": "selection-1", "approval_token": "forged"},
            call_id="call-1",
            context_generation=7,
            session_id="abc123abc123",
        )


def test_claim_crossing_pending_ttl_retains_authoritative_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    now = 0.0
    monkeypatch.setattr(pending_approvals.time, "monotonic", lambda: now)
    pending_id = _register()
    now = pending_approvals.TTL_SECONDS - 1
    record = _claim(pending_id)

    # When
    now = pending_approvals.TTL_SECONDS + 1
    completed = pending_approvals.complete(
        pending_id,
        record,
        {"run_id": "authoritative-run"},
    )

    # Then
    assert pending_approvals.recover(
        pending_id,
        session_id="abc123abc123",
        call_id="call-1",
        context_generation=7,
    ) == completed


def test_uncertain_claim_crossing_pending_ttl_retains_failure_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    now = 0.0
    monkeypatch.setattr(pending_approvals.time, "monotonic", lambda: now)
    pending_id = _register()
    now = pending_approvals.TTL_SECONDS - 1
    record = _claim(pending_id)

    # When
    now = pending_approvals.TTL_SECONDS + 1
    failed = pending_approvals.fail(pending_id, record, "dispatch uncertain")

    # Then
    assert pending_approvals.recover(
        pending_id,
        session_id="abc123abc123",
        call_id="call-1",
        context_generation=7,
    ) == failed


def test_release_after_pending_ttl_does_not_renew_human_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    now = 0.0
    monkeypatch.setattr(pending_approvals.time, "monotonic", lambda: now)
    pending_id = _register()
    now = pending_approvals.TTL_SECONDS - 1
    record = _claim(pending_id)

    # When
    now = pending_approvals.TTL_SECONDS + 1
    pending_approvals.release(pending_id, record)

    # Then
    with pytest.raises(pending_approvals.PendingApprovalError, match="unknown|expired|used"):
        pending_approvals.claim(
            pending_id,
            session_id="abc123abc123",
            call_id="call-1",
            context_generation=7,
        )


def test_in_flight_claim_is_not_time_purged_after_atomic_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    now = 0.0
    monkeypatch.setattr(pending_approvals.time, "monotonic", lambda: now)
    pending_id = _register()
    claimed_at = pending_approvals.TTL_SECONDS - 1
    now = claimed_at
    record = _claim(pending_id)

    # When
    now = claimed_at + pending_approvals.TTL_SECONDS + 1
    completed = pending_approvals.complete(
        pending_id,
        record,
        {"run_id": "long-dispatch"},
    )

    # Then
    assert completed.result["run_id"] == "long-dispatch"


def test_terminal_replay_expires_from_completion_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    now = 0.0
    monkeypatch.setattr(pending_approvals.time, "monotonic", lambda: now)
    pending_id = _register()
    now = 1.0
    record = _claim(pending_id)
    now = 2.0
    completed = pending_approvals.complete(pending_id, record, {"run_id": "authoritative-run"})

    # When
    now = 2.0 + pending_approvals.TTL_SECONDS
    at_boundary = pending_approvals.recover(
        pending_id,
        session_id="abc123abc123",
        call_id="call-1",
        context_generation=7,
    )
    now += 1
    after_boundary = pending_approvals.recover(
        pending_id,
        session_id="abc123abc123",
        call_id="call-1",
        context_generation=7,
    )

    # Then
    assert at_boundary == completed
    assert after_boundary is None


def test_in_flight_capacity_rejection_does_not_burn_pending_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(pending_approvals, "IN_FLIGHT_CAP", 1)
    first_id = _register()
    second_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": "/workspace/second.genkey", "selection_id": "selection-2"},
        call_id="call-2",
        context_generation=7,
        session_id="abc123abc123",
    )
    first = _claim(first_id)

    # When
    with pytest.raises(pending_approvals.PendingApprovalError, match="does not match"):
        _claim(second_id, call_id="call-2", session_id="different-session")
    with pytest.raises(pending_approvals.PendingApprovalError, match="capacity"):
        _claim(second_id, call_id="call-2")

    # Then
    pending_approvals.complete(first_id, first, {"run_id": "first-run"})
    second = _claim(second_id, call_id="call-2")
    assert second.call_id == "call-2"


def test_completed_approval_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pending_approvals, "TERMINAL_CAP", 2)
    identifiers: list[str] = []
    for index in range(3):
        pending_id = pending_approvals.register(
            action_kind="run_execute",
            args={"source": f"/workspace/case-{index}.genkey"},
            call_id=f"call-{index}",
            context_generation=7,
            session_id="abc123abc123",
        )
        record = pending_approvals.claim(
            pending_id,
            session_id="abc123abc123",
            call_id=f"call-{index}",
            context_generation=7,
        )
        pending_approvals.complete(pending_id, record, {"run_id": f"run-{index}"})
        identifiers.append(pending_id)

    assert pending_approvals.recover(
        identifiers[0],
        session_id="abc123abc123",
        call_id="call-0",
        context_generation=7,
    ) is None
    assert pending_approvals.recover(
        identifiers[2],
        session_id="abc123abc123",
        call_id="call-2",
        context_generation=7,
    ) is not None
