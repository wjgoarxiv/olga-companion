from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, workspace
from olga_companion.agent import chat, pending_approvals, session_token, tools
from olga_companion.llm.protocol import StreamResult, ToolCall
import olga_companion.sidecar as sidecar


class ExecutePayload(TypedDict):
    pending_id: str
    session_id: str
    call_id: str
    context_generation: int


class DispatchResult(TypedDict):
    run_id: str
    state: str


class UncertainDispatchProbeError(RuntimeError):
    pass


class FakeConversation:
    def add_user_message(self, text, images=None): ...

    def add_assistant_response(self, text, tool_calls=None, thought_signature=None): ...

    def add_tool_result(self, call_id, name, result): ...


class FakeApiClient:
    def __init__(self, result: StreamResult) -> None:
        self._result = result

    def create_conversation(self, model: str = "") -> FakeConversation:
        return FakeConversation()

    async def stream_generate(self, **kwargs) -> StreamResult:
        return self._result


@pytest.fixture(autouse=True)
def _clear_pending_approvals() -> None:
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()
    chat.set_client_builder(None)


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        event_type = ""
        data: dict = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if event_type:
            events.append((event_type, data))
    return events


def _new_session(api: TestClient) -> str:
    response = api.post("/api/chat/session", json={"title": ""}, headers=_headers())
    assert response.status_code == 200
    return str(response.json()["session_id"])


def _register_run(case: Path, session_id: str, call_id: str = "call-1") -> tuple[str, int]:
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": str(case), "timeout_s": 3600, "selection_id": "selection-1"},
        call_id=call_id,
        context_generation=generation,
        session_id=session_id,
    )
    return pending_id, generation


def _execute_payload(
    pending_id: str, session_id: str, generation: int, call_id: str = "call-1"
) -> ExecutePayload:
    return {
        "pending_id": pending_id,
        "session_id": session_id,
        "call_id": call_id,
        "context_generation": generation,
    }


def test_approval_keeps_generation_that_bound_the_active_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broader = tmp_path / "broader"
    old_root = broader / "old"
    old_root.mkdir(parents=True)
    case = old_root / "old.genkey"
    case.write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old_root))
    workspace.set_active_rel(case.name)
    captured_generation = workspace.context_generation()
    dispatched: list[tuple[str, dict]] = []
    original_append = chat.history.append
    switched = False

    def append_then_switch(session_id: str, record: dict) -> None:
        nonlocal switched
        original_append(session_id, record)
        if record.get("type") == "tool_call" and not switched:
            switched = True
            workspace.switch_root(broader)

    monkeypatch.setattr(chat.history, "append", append_then_switch)
    monkeypatch.setattr(
        sidecar.tools, "approval_display", lambda _name, _args, locale="ko": {}
    )
    monkeypatch.setattr(
        sidecar.tools,
        "dispatch",
        lambda name, args: dispatched.append((name, args)) or {"run_id": "wrong-run"},
    )
    chat.set_client_builder(
        lambda _provider, _model, _variant: FakeApiClient(
            StreamResult(
                tool_calls=[
                    ToolCall(
                        name="run_execute",
                        args={"timeout_s": 3600, "selection_id": "selection-1"},
                        call_id="call-context",
                    )
                ]
            )
        )
    )
    api = TestClient(sidecar.app)
    session_id = _new_session(api)

    streamed = api.post(
        "/api/chat",
        json={"session_id": session_id, "message": "run the active case"},
        headers=_headers(),
    )
    streamed_events = _parse_sse(streamed.text)
    assert any(event == "approval_required" for event, _data in streamed_events), streamed.text
    approval = next(data for event, data in streamed_events if event == "approval_required")
    current_generation = workspace.context_generation()
    executed = api.post(
        "/api/approvals/execute",
        json=_execute_payload(
            str(approval["pending_id"]), session_id, current_generation, "call-context"
        ),
        headers=_headers(),
    )

    assert executed.status_code == 409
    assert approval["context_generation"] == captured_generation
    assert dispatched == []


def test_successful_dispatch_replays_after_history_failure_without_redispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = _new_session(api)
    pending_id, generation = _register_run(case, session_id)
    dispatches: list[str] = []

    def successful_dispatch(_name: str, _args: dict) -> DispatchResult:
        dispatches.append("called")
        return {"run_id": "authoritative-run", "state": "running"}

    def fail_history(_session_id: str, _record: dict) -> None:
        raise OSError("audit storage unavailable")

    monkeypatch.setattr(sidecar.tools, "dispatch", successful_dispatch)
    monkeypatch.setattr(sidecar.history, "append", fail_history)
    payload = _execute_payload(pending_id, session_id, generation)

    with caplog.at_level("WARNING", logger="olga_companion.agent.approval_execution"):
        first = api.post("/api/approvals/execute", json=payload, headers=_headers())
    mismatch = api.post(
        "/api/approvals/execute",
        json={**payload, "session_id": "different-session"},
        headers=_headers(),
    )
    replay = api.post("/api/approvals/execute", json=payload, headers=_headers())

    assert first.status_code == 200
    assert first.json()["result"]["run_id"] == "authoritative-run"
    assert mismatch.status_code == 409
    assert replay.status_code == 200
    assert replay.json()["result"] == first.json()["result"]
    assert dispatches == ["called"]
    assert "audit record could not be persisted" in caplog.text


def test_dispatch_crossing_pending_ttl_replays_without_redispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    session_id = "abc123abc123"
    now = 0.0
    monkeypatch.setattr(pending_approvals.time, "monotonic", lambda: now)
    pending_id, generation = _register_run(case, session_id)
    dispatches: list[str] = []

    def successful_dispatch(_name: str, _args: dict) -> DispatchResult:
        nonlocal now
        dispatches.append("called")
        now = pending_approvals.TTL_SECONDS + 1
        return {"run_id": "authoritative-run", "state": "running"}

    monkeypatch.setattr(sidecar.tools, "dispatch", successful_dispatch)
    monkeypatch.setattr(sidecar.history, "append", lambda _session_id, _record: None)
    now = pending_approvals.TTL_SECONDS - 1
    payload = _execute_payload(pending_id, session_id, generation)

    # When
    first = sidecar.approval_execution.execute(**payload)
    replay = sidecar.approval_execution.execute(**payload)

    # Then
    assert first["result"]["run_id"] == "authoritative-run"
    assert replay == first
    assert dispatches == ["called"]


def test_pre_dispatch_error_releases_exact_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    api = TestClient(sidecar.app)
    session_id = _new_session(api)
    pending_id, generation = _register_run(case, session_id)
    attempts = 0

    def fail_then_succeed(_name: str, _args: dict) -> DispatchResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise tools.ToolPreDispatchError("preflight rejected")
        return {"run_id": "retry-run", "state": "running"}

    monkeypatch.setattr(sidecar.tools, "dispatch", fail_then_succeed)
    payload = _execute_payload(pending_id, session_id, generation)

    first = api.post("/api/approvals/execute", json=payload, headers=_headers())
    second = api.post("/api/approvals/execute", json=payload, headers=_headers())

    assert first.status_code == 400
    assert second.status_code == 200
    assert second.json()["result"]["run_id"] == "retry-run"
    assert attempts == 2


def test_schema_rejection_releases_claim_without_entering_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    api = TestClient(sidecar.app)
    session_id = _new_session(api)
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": str(case), "selection_id": "selection-1", "unexpected": True},
        call_id="call-1", session_id=session_id, context_generation=generation,
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["run_execute"], "handler", lambda args: calls.append(args) or {},
    )
    payload = _execute_payload(pending_id, session_id, generation)
    for _ in range(2):
        rejected = api.post("/api/approvals/execute", json=payload, headers=_headers())
        assert rejected.status_code == 400
        assert pending_approvals.is_actionable(pending_id, **{
            key: payload[key] for key in ("session_id", "call_id", "context_generation")
        })
    assert calls == []


def test_uncertain_dispatch_error_never_redispatches_exact_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = _new_session(api)
    pending_id, generation = _register_run(case, session_id)
    attempts = 0

    def uncertain_dispatch(_name: str, _args: dict) -> DispatchResult:
        nonlocal attempts
        attempts += 1
        raise UncertainDispatchProbeError("unknown post-dispatch failure")

    monkeypatch.setattr(sidecar.tools, "dispatch", uncertain_dispatch)
    payload = _execute_payload(pending_id, session_id, generation)

    first = api.post("/api/approvals/execute", json=payload, headers=_headers())
    second = api.post("/api/approvals/execute", json=payload, headers=_headers())

    assert first.status_code == 409
    assert second.status_code == 409
    assert attempts == 1
    assert "unknown post-dispatch failure" not in first.text
    assert "outcome could not be confirmed" in first.text


@pytest.mark.parametrize("failure", ["handler_error", "invalid_result", "cap_error", "forged_pre_dispatch"])
def test_post_handler_tool_error_is_sealed_across_replay_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = _new_session(api)
    pending_id, generation = _register_run(case, session_id)
    calls: list[str] = []

    def handler(_args: dict) -> dict:
        calls.append("action occurred")
        if failure == "handler_error":
            raise tools.ToolError("private post-action failure")
        if failure == "forged_pre_dispatch":
            raise tools.ToolPreDispatchError("private post-action failure")
        return {"unexpected": "private post-action failure"}

    monkeypatch.setattr(tools.TOOLS["run_execute"], "handler", handler)
    if failure == "invalid_result":
        monkeypatch.setattr(tools.TOOLS["run_execute"], "response_schema", {
            "type": "object", "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"], "additionalProperties": False,
        })
    if failure == "cap_error":
        def fail_cap(_result: dict) -> dict:
            raise tools.ToolError("private post-action failure")

        monkeypatch.setattr(tools, "_cap", fail_cap)
    payload = _execute_payload(pending_id, session_id, generation)
    first = api.post("/api/approvals/execute", json=payload, headers=_headers())
    second = api.post("/api/approvals/execute", json=payload, headers=_headers())
    assert first.status_code == second.status_code == 409
    assert first.json()["state"] == second.json()["state"] == "uncertain"
    assert first.json()["resume_allowed"] is False
    assert "private post-action failure" not in first.text
    assert calls == ["action occurred"]

    pending_approvals._PENDING.clear()
    pending_approvals._IN_FLIGHT.clear()
    pending_approvals._TERMINAL.clear()
    pending_approvals._restore()
    restarted = api.post("/api/approvals/execute", json=payload, headers=_headers())
    assert restarted.status_code == 409
    assert restarted.json()["state"] == "uncertain"
    assert calls == ["action occurred"]


def test_a_workspace_switch_cannot_land_between_an_approval_check_and_its_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Approved side effects are the only tools that mutate state; they hold the context
    # lock from the generation check until the handler returns, so a switch can only wait.
    import threading

    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    case = old_root / "old.genkey"
    case.write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")
    monkeypatch.delenv("OLGA_WORKSPACE_DIR", raising=False)
    config.set_workspace_root(str(old_root))
    workspace.set_active_rel(case.name)
    api = TestClient(sidecar.app)
    session_id = _new_session(api)
    pending_id, generation = _register_run(case, session_id)
    observed: dict[str, object] = {}

    def handler(_name: str, _args: dict) -> DispatchResult:
        switcher = threading.Thread(target=lambda: workspace.switch_root(new_root))
        switcher.start()
        switcher.join(timeout=0.5)
        observed["switch_finished_during_handler"] = not switcher.is_alive()
        observed["root_seen_by_handler"] = workspace.context_identity()[0]
        observed["switcher"] = switcher
        return {"run_id": "right-run", "state": "running"}

    monkeypatch.setattr(sidecar.tools, "dispatch", handler)

    executed = api.post(
        "/api/approvals/execute",
        json=_execute_payload(pending_id, session_id, generation),
        headers=_headers(),
    )
    observed["switcher"].join(timeout=3)  # type: ignore[attr-defined]

    assert executed.status_code == 200, executed.text
    assert observed["switch_finished_during_handler"] is False
    assert observed["root_seen_by_handler"] == old_root.resolve()
    assert workspace.context_identity()[0] == new_root.resolve()


def test_failed_payload_click_answers_the_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import fluid_table
    from olga_companion.agent import history

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        fluid_table, "databank_names", lambda *args, **kwargs: {"METHANE": "METHANE"}
    )
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    session_id = _new_session(api)
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="fluids_draft_mfl",
        args={
            "fluid_label": "SYN1",
            "components": [{"name": "METHANE", "mole_fraction": 1.0}],
            "model": "SRK",
            "temperatures": [-10.0, 50.0],
            "temperature_unit": "degC",
            "pressures": [0.0, 5.0],
            "pressure_unit": "furlong",
            "mfl_rel": "synthetic.mfl",
        },
        call_id="bad-1",
        session_id=session_id,
        context_generation=generation,
    )
    clicked = api.post(
        "/api/approvals/execute",
        json=_execute_payload(pending_id, session_id, generation, "bad-1"),
        headers=_headers(),
    )

    assert clicked.status_code == 200, clicked.text
    body = clicked.json()
    assert body["state"] == "failed"
    assert body["resume_allowed"] is False
    assert body["result"]["error"]
    answered = [
        record
        for record in history.read(session_id)
        if record.get("record") == "event"
        and record.get("type") == "tool_result"
        and record.get("call_id") == "bad-1"
    ]
    assert answered, "the model call must be answered with a tool_result"
    assert answered[0]["result"]["error"]
