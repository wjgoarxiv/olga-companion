from __future__ import annotations

import anyio
import pytest

from olga_companion import config
from olga_companion.agent import (
    approval_event_persistence,
    history,
    pending_approvals,
    runtime,
)


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "project_root", lambda: tmp_path)
    monkeypatch.setenv("OLGA_APPROVAL_JOURNAL_DIR", str(tmp_path / "approvals"))
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def test_continuation_run_approval_streams_and_reloads_server_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = history.new_session("continuation approval")
    spoofed_args = {
        "source": "/workspace/case.genkey",
        "selection_id": "selection-1",
        "runtime_id": "MODEL-SPOOF",
        "executable": "evil.exe",
    }
    trusted_display = {
        "case": "case.genkey",
        "selection_id": "selection-1",
        "runtime_id": "OLGA-2022.1",
        "executable": "OLGA-2022.1.0.exe",
        "output_target": "managed-run-sandbox",
        "source_sha256": "a" * 64,
        "timeout_s": 3600,
        "context_generation": 3,
    }

    async def provider_events(*_args, **_kwargs):
        yield runtime.AgentEvent(
            "approval_required",
            {
                "name": "run_execute",
                "args": spoofed_args,
                "call_id": "call-next-run",
                "context_generation": 3,
            },
        )

    monkeypatch.setattr(approval_event_persistence.runtime, "run_turn", provider_events)
    monkeypatch.setattr(
        approval_event_persistence.tools,
        "approval_display",
        lambda _name, _args, locale="ko": trusted_display,
    )
    emitted: list[dict] = []

    async def capture(event: dict) -> None:
        emitted.append(event)

    events = anyio.run(
        approval_event_persistence.persist_runtime_events,
        object(),
        "model",
        object(),
        session_id,
        {"turn_id": "turn-1", "request_id": "request-1"},
        capture,
    )

    streamed = events[0]["data"]
    persisted = next(
        record
        for record in history.read(session_id)
        if record.get("record") == "approval"
    )
    assert streamed["pending_id"] == persisted["pending_id"]
    assert emitted[0]["data"] == streamed
    assert streamed["display"] == persisted["display"] == trusted_display
    assert streamed["args"]["runtime_id"] == "MODEL-SPOOF"
    assert streamed["display"]["runtime_id"] == "OLGA-2022.1"
    assert "evil.exe" not in str(streamed["display"])
