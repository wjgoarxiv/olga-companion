"""T2 gate — out-of-band approval tokens: single-use, TTL, digest-bound, human-mint-only."""
from __future__ import annotations

from typing import cast

import pytest

from olga_companion.agent import approvals


def _payload():
    return {"source": "/ws/case.genkey", "timeout_s": 3600}


def test_mint_then_consume_once():
    minted = approvals.mint("run_execute", _payload())
    assert minted["token"] and minted["expires_at"] > 0
    approvals.consume(minted["token"], "run_execute", _payload())  # no raise
    with pytest.raises(approvals.ApprovalError, match="unknown|used"):
        approvals.consume(minted["token"], "run_execute", _payload())


def test_digest_binds_exact_payload():
    minted = approvals.mint("run_execute", _payload())
    tampered = dict(_payload(), timeout_s=1)
    with pytest.raises(approvals.ApprovalError, match="match"):
        approvals.consume(minted["token"], "run_execute", tampered)
    # A mismatch attempt must not burn the legitimate approval.
    approvals.consume(minted["token"], "run_execute", _payload())


def test_action_kind_is_part_of_the_digest():
    minted = approvals.mint("run_execute", _payload())
    with pytest.raises(approvals.ApprovalError, match="match"):
        approvals.consume(minted["token"], "opc_write", _payload())


def test_expired_token_rejected(monkeypatch):
    minted = approvals.mint("run_execute", _payload())
    import olga_companion.agent.approvals as mod

    monkeypatch.setattr(mod.time, "time", lambda: minted["expires_at"] + 1)
    with pytest.raises(approvals.ApprovalError, match="expired"):
        approvals.consume(minted["token"], "run_execute", _payload())


def test_unknown_token_rejected():
    with pytest.raises(approvals.ApprovalError, match="unknown|used"):
        approvals.consume("not-a-real-token", "run_execute", _payload())


def test_mint_requires_action_and_payload():
    with pytest.raises(approvals.ApprovalError):
        approvals.mint("", _payload())
    with pytest.raises(approvals.ApprovalError):
        approvals.mint("run_execute", cast(dict[str, str], None))


def test_revoke_all_is_locked_and_returns_count():
    first = approvals.mint("run_execute", {"source": "one"})
    second = approvals.mint("run_execute", {"source": "two"})

    assert approvals.revoke_all() == 2
    assert approvals.revoke_all() == 0
    for minted, source in ((first, "one"), (second, "two")):
        with pytest.raises(approvals.ApprovalError):
            approvals.consume(minted["token"], "run_execute", {"source": source})


def test_generation_bound_token_rejects_other_generation_without_burning_it():
    minted = approvals.mint("run_execute", _payload(), context_generation=7)

    with pytest.raises(approvals.ApprovalError, match="workspace context"):
        approvals.consume(
            minted["token"], "run_execute", _payload(), context_generation=8
        )

    approvals.consume(
        minted["token"], "run_execute", _payload(), context_generation=7
    )


def test_production_consume_rejects_unbound_direct_token():
    minted = approvals.mint("run_execute", _payload())

    with pytest.raises(approvals.ApprovalError, match="workspace context"):
        approvals.consume(
            minted["token"], "run_execute", _payload(), context_generation=0
        )
