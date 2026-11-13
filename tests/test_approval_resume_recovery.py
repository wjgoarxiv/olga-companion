from __future__ import annotations

import importlib
import asyncio
from pathlib import Path
from typing import TypedDict

import pytest
from fastapi.testclient import TestClient

from olga_companion import config, workspace
from olga_companion.agent import chat, history, pending_approvals, session_token
from olga_companion.llm.protocol import StreamResult, ToolCall
import olga_companion.sidecar as sidecar


class ExecutePayload(TypedDict):
    pending_id: str
    session_id: str
    call_id: str
    context_generation: int


class ResumeConversation:
    def add_user_message(self, _text: str, _images: list[bytes] | None = None) -> None:
        pass

    def add_assistant_response(
        self,
        _text: str,
        _tool_calls: list[ToolCall] | None = None,
        _thought_signature: str | None = None,
    ) -> None:
        pass

    def add_tool_result(self, _call_id: str, _name: str, _result: str) -> None:
        pass


class ResumeApiClient:
    def __init__(self) -> None:
        self.generations = 0

    def create_conversation(self, _model: str = "") -> ResumeConversation:
        return ResumeConversation()

    async def stream_generate(self, **_kwargs) -> StreamResult:
        self.generations += 1
        return StreamResult(text="The approved run is now being monitored.")


@pytest.fixture(autouse=True)
def _isolated_approval_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("OLGA_APPROVAL_JOURNAL_DIR", str(tmp_path / "approval-journal"))
    monkeypatch.setattr(config, "project_root", lambda: tmp_path)
    pending_approvals.revoke_all()
    chat.set_client_builder(None)
    yield
    pending_approvals.revoke_all()
    chat.set_client_builder(None)


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _register(session_id: str = "abc123abc123") -> ExecutePayload:
    case = config.workspace_root() / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": str(case), "timeout_s": 3600, "selection_id": "selection-1"},
        call_id="call-approved-run",
        context_generation=generation,
        session_id=session_id,
    )
    return {
        "pending_id": pending_id,
        "session_id": session_id,
        "call_id": "call-approved-run",
        "context_generation": generation,
    }


def _record_original_identity(
    session_id: str, payload: ExecutePayload, **identity: object
) -> None:
    history.append(
        session_id,
        {
            "record": "approval",
            "pending_id": payload["pending_id"],
            "call_id": payload["call_id"],
            "name": "run_execute",
            "state": "pending",
            "workspace_generation": payload["context_generation"],
            **identity,
        },
    )


def test_terminal_action_receipt_survives_pending_store_restart() -> None:
    payload = _register()
    pending = pending_approvals.claim(**payload)
    pending_approvals.complete(
        payload["pending_id"], pending, {"run_id": "durable-run", "state": "running"}
    )

    importlib.reload(pending_approvals)
    recovered = pending_approvals.recover(**payload)

    assert isinstance(recovered, pending_approvals.CompletedApproval)
    assert recovered.result == {"run_id": "durable-run", "state": "running"}


def test_restart_releases_unfinished_resume_lease_for_history_repair() -> None:
    payload = _register()
    pending = pending_approvals.claim(**payload)
    pending_approvals.complete(payload["pending_id"], pending, {"run_id": "resume-run"})
    _outcome, acquired = pending_approvals.begin_resume(
        payload["pending_id"],
        session_id=payload["session_id"],
        call_id=payload["call_id"],
        context_generation=payload["context_generation"],
    )
    assert acquired is True

    importlib.reload(pending_approvals)
    recovered = pending_approvals.recover(**payload)

    assert isinstance(recovered, pending_approvals.CompletedApproval)
    assert recovered.resume_state == "pending"


def test_dispatch_receipt_stays_finalizing_until_assistant_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = history.new_session("finalizing approval")
    payload = _register(session_id)
    history.append(
        session_id,
        {
            "record": "approval",
            "pending_id": payload["pending_id"],
            "call_id": payload["call_id"],
            "name": "run_execute",
            "state": "pending",
            "lifecycle": "awaiting-approval",
            "provider": "openai",
            "model": "test-model",
            "workspace_generation": payload["context_generation"],
        },
    )
    resume_client = ResumeApiClient()
    chat.set_client_builder(lambda _provider, _model, _variant: resume_client)
    monkeypatch.setattr(
        sidecar.tools,
        "dispatch",
        lambda _name, _args: {"run_id": "finalizing-run", "state": "running"},
    )
    client = TestClient(sidecar.app)

    executed = client.post("/api/approvals/execute", json=payload, headers=_headers())
    before_resume = history.read(session_id)
    resumed = client.post("/api/approvals/resume", json=payload, headers=_headers())
    after_resume = history.read(session_id)

    before_states = [
        record.get("state") for record in before_resume if record.get("record") == "approval"
    ]
    after_approvals = [record for record in after_resume if record.get("record") == "approval"]
    assert executed.json()["state"] == "resume_pending"
    assert before_states[-1] == "resume_pending"
    assert "completed" not in before_states
    assert resumed.status_code == 200
    assert after_approvals[-1]["state"] == "completed"
    assert after_approvals[-1]["lifecycle"] == "completed"
    assert after_approvals[-1]["resume_allowed"] is False


def test_history_failure_resume_is_actionable_and_exact_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = history.new_session("resume after approval")
    payload = _register(session_id)
    _record_original_identity(session_id, payload, provider="openai", model="test-model")
    resume_client = ResumeApiClient()
    chat.set_client_builder(lambda _provider, _model, _variant: resume_client)
    monkeypatch.setattr(
        sidecar.tools,
        "dispatch",
        lambda _name, _args: {"run_id": "receipt-run", "state": "running"},
    )
    original_append = sidecar.history.append
    audit_failed = False

    def fail_first_audit(target_session_id: str, record: dict) -> None:
        nonlocal audit_failed
        if record.get("record") == "approval" and record.get("state") == "resume_pending" and not audit_failed:
            audit_failed = True
            raise OSError("audit disk unavailable")
        original_append(target_session_id, record)

    monkeypatch.setattr(sidecar.history, "append", fail_first_audit)
    execute_response = TestClient(sidecar.app).post(
        "/api/approvals/execute", json=payload, headers=_headers()
    )

    first_resume = TestClient(sidecar.app).post(
        "/api/approvals/resume", json=payload, headers=_headers()
    )
    replay_resume = TestClient(sidecar.app).post(
        "/api/approvals/resume", json=payload, headers=_headers()
    )

    records = history.read(session_id)
    tool_results = [record for record in records if record.get("type") == "tool_result"]
    assistants = [
        record
        for record in records
        if record.get("record") == "assistant"
        and record.get("text") == "The approved run is now being monitored."
    ]
    assert execute_response.status_code == 200
    assert execute_response.json()["state"] == "resume_pending"
    assert execute_response.json()["result"]["run_id"] == "receipt-run"
    assert first_resume.status_code == replay_resume.status_code == 200
    assert len(tool_results) == len(assistants) == resume_client.generations == 1


def test_history_read_failure_releases_resume_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _register()
    pending = pending_approvals.claim(**payload)
    pending_approvals.complete(payload["pending_id"], pending, {"run_id": "read-fail"})
    monkeypatch.setattr(history, "read", lambda _session_id: (_ for _ in ()).throw(OSError("offline")))

    with pytest.raises(OSError, match="offline"):
        asyncio.run(sidecar.approval_execution.resume(**payload))
    recovered = pending_approvals.recover(**payload)

    assert isinstance(recovered, pending_approvals.CompletedApproval)
    assert recovered.resume_state == "pending"


def test_resume_pending_stream_never_synthesizes_terminal_done() -> None:
    payload = _register()
    pending = pending_approvals.claim(**payload)
    pending_approvals.complete(payload["pending_id"], pending, {"run_id": "leased"})
    _outcome, acquired = pending_approvals.begin_resume(
        payload["pending_id"],
        session_id=payload["session_id"],
        call_id=payload["call_id"],
        context_generation=payload["context_generation"],
    )
    assert acquired is True

    streamed = TestClient(sidecar.app).post(
        "/api/approvals/resume", json=payload, headers=_headers()
    )

    assert streamed.status_code == 200
    assert "event: done" not in streamed.text
    assert "resume_pending" in streamed.text


def test_post_generation_history_failure_seals_uncertain_without_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = history.new_session("uncertain continuation")
    payload = _register(session_id)
    history.append(
        session_id,
        {
            "record": "approval",
            "pending_id": payload["pending_id"],
            "call_id": payload["call_id"],
            "name": "run_execute",
            "state": "pending",
            "provider": "openai",
            "model": "test-model",
            "workspace_generation": payload["context_generation"],
        },
    )
    resume_client = ResumeApiClient()
    chat.set_client_builder(lambda _provider, _model, _variant: resume_client)
    monkeypatch.setattr(
        sidecar.tools,
        "dispatch",
        lambda _name, _args: {"run_id": "uncertain-run", "state": "running"},
    )
    api = TestClient(sidecar.app)
    assert api.post("/api/approvals/execute", json=payload, headers=_headers()).status_code == 200
    original_append = history.append

    def fail_assistant(target_session_id: str, record: dict) -> None:
        if record.get("record") == "assistant":
            raise OSError("assistant audit unavailable")
        original_append(target_session_id, record)

    monkeypatch.setattr(history, "append", fail_assistant)

    first = api.post("/api/approvals/resume", json=payload, headers=_headers())
    replay = api.post("/api/approvals/resume", json=payload, headers=_headers())
    recovered = pending_approvals.recover(**payload)

    assert isinstance(recovered, pending_approvals.CompletedApproval)
    assert recovered.resume_state == "uncertain"
    assert resume_client.generations == 1
    assert "event: done" not in first.text + replay.text
    assert '"state": "uncertain"' in replay.text


def _execute_once(monkeypatch: pytest.MonkeyPatch, payload: ExecutePayload) -> tuple[TestClient, list[str]]:
    dispatched: list[str] = []

    def dispatch(name: str, _args: dict) -> dict:
        dispatched.append(name)
        return {"run_id": "identity-run", "state": "running"}

    monkeypatch.setattr(sidecar.tools, "dispatch", dispatch)
    api = TestClient(sidecar.app)
    assert api.post("/api/approvals/execute", json=payload, headers=_headers()).status_code == 200
    return api, dispatched


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"provider": "openai"},
        {"model": "test-model"},
        {"provider": "openai", "model": "   "},
        {"provider": "not-a-provider", "model": "test-model"},
        {"provider": ["openai"], "model": "test-model"},
        {"provider": "openai", "model": 7},
    ],
)
def test_missing_or_malformed_original_identity_never_reaches_any_provider(
    monkeypatch: pytest.MonkeyPatch, identity: dict[str, object]
) -> None:
    session_id = history.new_session("identity-less approval")
    payload = _register(session_id)
    _record_original_identity(session_id, payload, **identity)
    built: list[tuple[str, str, str]] = []
    resume_client = ResumeApiClient()

    def builder(provider: str, model: str, variant: str) -> ResumeApiClient:
        built.append((provider, model, variant))
        return resume_client

    chat.set_client_builder(builder)
    api, dispatched = _execute_once(monkeypatch, payload)

    first = api.post("/api/approvals/resume", json=payload, headers=_headers())
    replay = api.post("/api/approvals/resume", json=payload, headers=_headers())
    recovered = pending_approvals.recover(**payload)

    assert built == [] and resume_client.generations == 0
    assert dispatched == ["run_execute"]
    assert isinstance(recovered, pending_approvals.CompletedApproval)
    assert recovered.resume_state == "uncertain"
    assert "event: done" not in first.text + replay.text
    assert "does not record a" in first.text
    assert '"resume_allowed": false' in replay.text


def test_resume_uses_only_the_original_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = history.new_session("copilot approval")
    payload = _register(session_id)
    _record_original_identity(session_id, payload, provider="copilot", model="copilot-model")
    built: list[tuple[str, str, str]] = []
    resume_client = ResumeApiClient()

    def builder(provider: str, model: str, variant: str) -> ResumeApiClient:
        built.append((provider, model, variant))
        return resume_client

    chat.set_client_builder(builder)
    api, dispatched = _execute_once(monkeypatch, payload)

    assert api.post("/api/approvals/resume", json=payload, headers=_headers()).status_code == 200

    assert built == [("copilot", "copilot-model", "")]
    assert dispatched == ["run_execute"] and resume_client.generations == 1


def test_disconnected_original_provider_stays_retryable_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = history.new_session("disconnected approval")
    payload = _register(session_id)
    _record_original_identity(session_id, payload, provider="copilot", model="copilot-model")
    built: list[str] = []
    resume_client = ResumeApiClient()
    connected = False

    def builder(provider: str, _model: str, _variant: str) -> ResumeApiClient | None:
        built.append(provider)
        return resume_client if connected else None

    chat.set_client_builder(builder)
    api, dispatched = _execute_once(monkeypatch, payload)

    offline = api.post("/api/approvals/resume", json=payload, headers=_headers())
    connected = True
    online = api.post("/api/approvals/resume", json=payload, headers=_headers())

    assert "'copilot' is not connected" in offline.text
    assert '"resume_allowed": true' in offline.text
    assert "event: done" in online.text
    assert set(built) == {"copilot"}
    assert dispatched == ["run_execute"] and resume_client.generations == 1


def test_an_empty_recorded_model_is_a_valid_identity_for_a_provider_with_an_empty_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a provider whose catalog is empty legitimately records model "".
    session_id = history.new_session("empty catalog approval")
    payload = _register(session_id)
    _record_original_identity(session_id, payload, provider="copilot", model="")
    built: list[tuple[str, str, str]] = []
    resume_client = ResumeApiClient()

    def builder(provider: str, model: str, variant: str) -> ResumeApiClient:
        built.append((provider, model, variant))
        return resume_client

    chat.set_client_builder(builder)
    api, dispatched = _execute_once(monkeypatch, payload)

    # When / Then: the continuation runs with exactly that identity.
    assert api.post("/api/approvals/resume", json=payload, headers=_headers()).status_code == 200
    assert built == [("copilot", "", "")] and dispatched == ["run_execute"] and resume_client.generations == 1


def test_a_sealed_identity_failure_is_recorded_so_history_does_not_offer_a_dead_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = history.new_session("sealed approval")
    payload = _register(session_id)
    _record_original_identity(session_id, payload)  # no identity at all
    chat.set_client_builder(lambda *_: ResumeApiClient())
    api, _ = _execute_once(monkeypatch, payload)

    api.post("/api/approvals/resume", json=payload, headers=_headers())

    receipts = [r for r in history.read(session_id) if r.get("record") == "approval" and r.get("pending_id") == payload["pending_id"]]
    assert receipts[-1]["state"] == "uncertain" and receipts[-1]["resume_allowed"] is False
