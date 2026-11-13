"""T9b RED: a Codex 400 model_not_found retries once, is remembered, and leaves the picker."""
from __future__ import annotations

import pytest

from olga_companion.llm import provider_runtime_status
from olga_companion.llm.codex_oauth_models import (
    SUPPORTED_MODELS,
    codex_models_to_try,
    is_codex_model_not_found,
)
from olga_companion.llm.openai_responses_adapter import OpenAIResponsesApiClient


@pytest.fixture(autouse=True)
def _clean_registry():
    provider_runtime_status.reset_all()
    yield
    provider_runtime_status.reset_all()


MODEL_400_BODY = (
    '{"error": {"code": "model_not_found", "message": '
    "\"'gpt-6.1-sol' model is not supported when using Codex "
    'with a ChatGPT account"}}'
)


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class _FakeResp:
    def __init__(self, status, text="", chunks=()):
        self.status = status
        self._text = text
        self.content = _FakeContent(chunks)

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, script):
        self._script = script
        self.models: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, json=None, headers=None):
        self.models.append(json["model"])
        item = self._script[len(self.models) - 1]
        if isinstance(item, Exception):
            raise item
        return item


def _ok_chunks():
    return (
        b'event: response.output_text.delta\ndata: {"delta": "hi"}\n\n',
        b'event: response.completed\ndata: {"response": {"id": "r1"}}\n\n',
    )


class _Conversation:
    def get_request_payload(self):
        return []


def _client_and_session(monkeypatch, script):
    session = _FakeSession(script)
    monkeypatch.setattr(
        "olga_companion.net.aiohttp_session", lambda **kwargs: session
    )
    client = OpenAIResponsesApiClient(base_url="http://localhost", access_token="t")
    return client, session


async def _generate(client):
    return await client.stream_generate(
        conversation=_Conversation(), model="gpt-6.1-sol", system_instruction="s"
    )


def test_order_prefers_requested_then_supported():
    assert codex_models_to_try("gpt-6.1-sol")[0] == "gpt-6.1-sol"
    assert set(codex_models_to_try("gpt-6.1-sol")) == set(SUPPORTED_MODELS)


def test_classifier_needs_400_plus_model_marker():
    assert is_codex_model_not_found(
        ValueError(f"Responses API error 400: {MODEL_400_BODY}"), "gpt-6.1-sol"
    )
    assert not is_codex_model_not_found(
        ValueError("Responses API error 400: bad tool schema"), "gpt-6.1-sol"
    )
    assert not is_codex_model_not_found(
        ValueError("Rate limited (429) on gpt-6.1-sol"), "gpt-6.1-sol"
    )


def test_classifier_ignores_missing_item_without_model_id():
    assert not is_codex_model_not_found(
        ValueError(
            "Responses API error 400: {'error': {'message': "
            "'previous response does not exist'}}"
        ),
        "gpt-6.1-sol",
    )
    assert not is_codex_model_not_found(
        ValueError("Responses API error 400: {'error': {'code': 'invalid_request'}}"),
        "gpt-6.1-sol",
    )


def test_classifier_accepts_code_markers_without_id():
    assert is_codex_model_not_found(
        ValueError("Responses API error 400: model_not_found"), "gpt-6.1-sol"
    )
    assert is_codex_model_not_found(
        ValueError("Responses API error 400: model_not_supported"), "gpt-6.1-sol"
    )
    assert not is_codex_model_not_found(
        ValueError("model_not_found"), "gpt-6.1-sol"
    )


def test_model_not_found_retries_once_with_next_supported(monkeypatch):
    client, session = _client_and_session(
        monkeypatch, [_FakeResp(400, MODEL_400_BODY), _FakeResp(200, "", _ok_chunks())]
    )

    import asyncio

    result = asyncio.run(_generate(client))

    assert result.text == "hi"
    assert session.models == ["gpt-6.1-sol", SUPPORTED_MODELS[1]]
    assert "gpt-6.1-sol" in provider_runtime_status.unsupported_models("openai")
    assert provider_runtime_status.pop_model_fallback("openai") == {
        "provider": "openai",
        "requested": "gpt-6.1-sol",
        "used": SUPPORTED_MODELS[1],
    }


def test_second_model_not_found_raises_without_further_retry(monkeypatch):
    client, session = _client_and_session(
        monkeypatch, [_FakeResp(400, MODEL_400_BODY), _FakeResp(400, MODEL_400_BODY)]
    )

    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(_generate(client))
    assert session.models == ["gpt-6.1-sol", SUPPORTED_MODELS[1]]


def test_fallback_gets_full_transport_attempts(monkeypatch):
    client, session = _client_and_session(
        monkeypatch,
        [
            RuntimeError("transport blew up"),
            _FakeResp(400, MODEL_400_BODY),
            _FakeResp(200, "", _ok_chunks()),
        ],
    )

    import asyncio

    result = asyncio.run(_generate(client))

    assert result.text == "hi"
    assert session.models == ["gpt-6.1-sol", "gpt-6.1-sol", SUPPORTED_MODELS[1]]
    assert provider_runtime_status.pop_model_fallback("openai") == {
        "provider": "openai",
        "requested": "gpt-6.1-sol",
        "used": SUPPORTED_MODELS[1],
    }


def test_transport_exhaustion_raises_without_fallback_notice(monkeypatch):
    client, session = _client_and_session(
        monkeypatch, [RuntimeError("boom-1"), RuntimeError("boom-2")]
    )

    import asyncio

    with pytest.raises(ValueError, match="failed after"):
        asyncio.run(_generate(client))
    assert session.models == ["gpt-6.1-sol", "gpt-6.1-sol"]
    assert provider_runtime_status.pop_model_fallback("openai") is None


def test_rejected_model_leaves_picker_and_default(monkeypatch):
    from olga_companion.llm import catalog

    provider_runtime_status.record_unsupported_model("openai", "gpt-6.1-sol")
    assert "gpt-6.1-sol" not in {m["id"] for m in catalog.available_models("openai")}
    assert catalog.default_model("openai") != "gpt-6.1-sol"


def test_fallback_notice_names_models_once_in_each_language():
    from olga_companion.agent import chat as chat_module

    provider_runtime_status.record_model_fallback(
        "openai", requested="gpt-6.1-sol", used="gpt-6-astra"
    )
    ko = chat_module._model_fallback_notice("openai", "ko")
    assert "GPT-6.1 Sol" in ko
    assert "GPT-6 Astra" in ko
    assert "바꿨습니다" in ko
    assert chat_module._model_fallback_notice("openai", "ko") is None

    provider_runtime_status.record_model_fallback(
        "openai", requested="gpt-6.1-sol", used="gpt-6-astra"
    )
    en = chat_module._model_fallback_notice("openai", "en")
    assert "This account cannot use GPT-6.1 Sol" in en
    assert chat_module._model_fallback_notice("openai", "en") is None


def test_no_fallback_means_no_notice():
    from olga_companion.agent import chat as chat_module

    assert chat_module._model_fallback_notice("openai", "ko") is None


def test_steer_starts_past_rejected_model_with_notice():
    from olga_companion.agent import chat as chat_module

    provider_runtime_status.record_unsupported_model("openai", "gpt-6.1-sol")
    assert (
        chat_module.steer_past_rejected_model("openai", "gpt-6.1-sol")
        == "gpt-6-astra"
    )
    assert provider_runtime_status.pop_model_fallback("openai") == {
        "provider": "openai",
        "requested": "gpt-6.1-sol",
        "used": "gpt-6-astra",
    }


class _TurnConversation:
    def add_user_message(self, message, images=None):
        pass

    def add_assistant_response(self, text, tool_calls=None, thought_signature=None):
        pass

    def add_tool_result(self, call_id, name, result):
        pass


class _TurnClient:
    def __init__(self, script):
        self._script = list(script)
        self.seen_models: list[str] = []

    def create_conversation(self, model=""):
        return _TurnConversation()

    async def stream_generate(self, **kwargs):
        self.seen_models.append(kwargs.get("model"))
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def _collect_turn(session_id, **kwargs):
    from olga_companion.agent import chat as chat_module

    return [
        event
        async for event in chat_module._run_locked_turn(session_id, "hi", **kwargs)
    ]


def _turn_session(tmp_path, monkeypatch):
    import asyncio

    from olga_companion.agent import history

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    return history.new_session("steer probe")


def test_rejected_model_turn_runs_steered_with_notice(tmp_path, monkeypatch):
    import asyncio

    from olga_companion.llm.protocol import StreamResult

    provider_runtime_status.record_unsupported_model("openai", "gpt-6.1-sol")
    client = _TurnClient([StreamResult(text="answer")])
    monkeypatch.setattr(
        "olga_companion.agent.chat._client_builder",
        lambda _p, _m, _v: client,
        raising=False,
    )
    session_id = _turn_session(tmp_path, monkeypatch)

    events = asyncio.run(
        _collect_turn(
            session_id,
            provider="openai",
            model="gpt-6.1-sol",
            variant="medium",
            locale="ko",
        )
    )

    assert client.seen_models == ["gpt-6-astra"]
    texts = [e.data.get("text", "") for e in events if e.type == "text"]
    assert any("GPT-6 Astra" in text for text in texts)
    assert provider_runtime_status.pop_model_fallback("openai") is None


def test_failed_turn_discards_fallback_notice(tmp_path, monkeypatch):
    import asyncio

    provider_runtime_status.record_model_fallback(
        "openai", requested="gpt-6.1-sol", used="gpt-6-astra"
    )
    client = _TurnClient([RuntimeError("transport down")])
    monkeypatch.setattr(
        "olga_companion.agent.chat._client_builder",
        lambda _p, _m, _v: client,
        raising=False,
    )
    session_id = _turn_session(tmp_path, monkeypatch)

    events = asyncio.run(
        _collect_turn(
            session_id,
            provider="openai",
            model="gpt-6-astra",
            variant="medium",
            locale="ko",
        )
    )

    assert any(e.type == "error" for e in events)
    texts = [e.data.get("text", "") for e in events if e.type == "text"]
    assert not any("GPT-6 Astra" in text for text in texts)
    assert provider_runtime_status.pop_model_fallback("openai") is None


def test_resume_uses_steered_model_without_failed_round_trip(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from olga_companion import config as app_config
    from olga_companion import workspace
    from olga_companion.agent import chat as chat_module
    from olga_companion.agent import history, pending_approvals, session_token
    from olga_companion.llm.protocol import StreamResult
    import olga_companion.sidecar as sidecar

    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_config, "project_root", lambda: tmp_path)
    pending_approvals.revoke_all()
    try:
        from olga_companion.agent import approval_continuation

        assert hasattr(approval_continuation, "resume")
        session_id = history.new_session("resume steer")
        case = tmp_path / "case.genkey"
        case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
        generation = workspace.context_generation()
        pending_id = pending_approvals.register(
            action_kind="run_execute",
            args={
                "source": str(case),
                "timeout_s": 3600,
                "selection_id": "selection-1",
            },
            call_id="call-1",
            context_generation=generation,
            session_id=session_id,
        )
        history.append(
            session_id,
            {
                "record": "approval",
                "pending_id": pending_id,
                "call_id": "call-1",
                "name": "run_execute",
                "state": "pending",
                "workspace_generation": generation,
                "provider": "openai",
                "model": "gpt-6.1-sol",
                "locale": "ko",
            },
        )
        provider_runtime_status.record_unsupported_model("openai", "gpt-6.1-sol")

        seen: list[str] = []

        class ResumeClient:
            def create_conversation(self, model=""):
                return _TurnConversation()

            async def stream_generate(self, **kwargs):
                seen.append(kwargs.get("model"))
                return StreamResult(text="resumed")

        chat_module.set_client_builder(
            lambda _p, _m, _v: ResumeClient()
        )
        monkeypatch.setattr(
            sidecar.tools, "dispatch", lambda _n, _a: {"run_id": "r", "state": "running"}
        )
        api = TestClient(sidecar.app)
        headers = {"X-Session-Token": session_token.boot_token()}
        payload = {
            "pending_id": pending_id,
            "session_id": session_id,
            "call_id": "call-1",
            "context_generation": generation,
        }
        executed = api.post("/api/approvals/execute", json=payload, headers=headers)
        assert executed.status_code == 200
        resumed = api.post("/api/approvals/resume", json=payload, headers=headers)

        assert resumed.status_code == 200
        assert seen == ["gpt-6-astra"]
        assert provider_runtime_status.pop_model_fallback("openai") is None
    finally:
        pending_approvals.revoke_all()
        chat_module.set_client_builder(None)


def test_steer_leaves_clean_and_fully_rejected_models_alone():
    from olga_companion.agent import chat as chat_module

    assert (
        chat_module.steer_past_rejected_model("openai", "gpt-6.1-sol")
        == "gpt-6.1-sol"
    )
    assert provider_runtime_status.pop_model_fallback("openai") is None
    for model in SUPPORTED_MODELS:
        provider_runtime_status.record_unsupported_model("openai", model)
    assert (
        chat_module.steer_past_rejected_model("openai", SUPPORTED_MODELS[0])
        == SUPPORTED_MODELS[0]
    )
    assert provider_runtime_status.pop_model_fallback("openai") is None
