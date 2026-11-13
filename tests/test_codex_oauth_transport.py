"""SSE and HTTP-error characterization tests for the Codex transport."""

from __future__ import annotations

import json
from collections.abc import Iterable
from types import TracebackType
from typing import Any

import httpx
import pytest

from olga_companion.llm import codex_oauth


class _Credentials:
    access_token = "secret-access-token"
    account_id = "account-id"


class _Response:
    def __init__(self, status_code: int, events: Iterable[dict[str, str]]) -> None:
        self.status_code = status_code
        self._lines = [f"data: {json.dumps(event)}" for event in events]
        self.read_called = False

    def __enter__(self) -> _Response:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def iter_lines(self) -> Iterable[str]:
        return iter(self._lines)

    def read(self) -> bytes:
        self.read_called = True
        return b""

    def json(self) -> dict[str, str]:
        return {}


class _Client:
    response = _Response(200, ())

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self) -> _Client:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def stream(
        self,
        _method: str,
        _url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> _Response:
        del json, headers
        return self.response


def _patch_transport(monkeypatch: pytest.MonkeyPatch, response: _Response) -> None:
    _Client.response = response
    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", lambda: _Credentials())
    monkeypatch.setattr(codex_oauth.httpx, "Client", _Client)


def test_sse_keeps_reasoning_and_output_channels_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given interleaved reasoning-summary and visible-output SSE events.
    response = _Response(
        200,
        (
            {"type": "response.reasoning_summary_text.delta", "delta": "thinking"},
            {"type": "response.output_text.delta", "delta": "hel"},
            {"type": "response.output_text.delta", "delta": "lo"},
        ),
    )
    _patch_transport(monkeypatch, response)
    output: list[str] = []
    reasoning: list[str] = []

    # When the synchronous model call consumes the stream.
    result = codex_oauth.call_codex_model(
        system_prompt="system",
        user_prompt="user",
        model=codex_oauth.DEFAULT_MODEL,
        variant="low",
        on_delta=output.append,
        on_reasoning_delta=reasoning.append,
    )

    # Then only visible output is returned while each callback gets its own channel.
    assert result == "hello"
    assert output == ["hel", "lo"]
    assert reasoning == ["thinking"]


@pytest.mark.parametrize(
    ("status_code", "message", "relogin_required"),
    (
        (401, "codex 인증이 만료되었습니다. 다시 로그인해 주세요.", True),
        (429, "codex 사용량 한도에 도달했습니다. 잠시 후 다시 시도하세요.", False),
        (503, "codex 모델 호출 실패 (HTTP 503)", False),
    ),
)
def test_http_errors_keep_operator_safe_mapping(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    message: str,
    relogin_required: bool,
) -> None:
    # Given a failed Responses endpoint status and an auth-failure marker spy.
    response = _Response(status_code, ())
    _patch_transport(monkeypatch, response)
    marked: list[bool] = []
    monkeypatch.setattr(codex_oauth, "_mark_runtime_auth_failure", lambda: marked.append(True))

    # When the model call maps the endpoint failure.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth.call_codex_model(
            system_prompt="system",
            user_prompt="user",
            model=codex_oauth.DEFAULT_MODEL,
            variant="low",
        )

    # Then the exact safe message/flag is preserved and no token leaks.
    assert str(captured.value) == message
    assert captured.value.relogin_required is relogin_required
    assert marked == ([True] if status_code == 401 else [])
    assert _Credentials.access_token not in str(captured.value)


def test_network_error_keeps_typed_operator_safe_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a client factory that fails before a response exists.
    class FailingClient:
        def __init__(self, *, timeout: float) -> None:
            raise httpx.ConnectError(f"network rejected token {_Credentials.access_token}")

    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", lambda: _Credentials())
    monkeypatch.setattr(codex_oauth.httpx, "Client", FailingClient)

    # When the model call maps the network failure.
    with pytest.raises(codex_oauth.CodexAuthError) as captured:
        codex_oauth.call_codex_model(
            system_prompt="system",
            user_prompt="user",
            model=codex_oauth.DEFAULT_MODEL,
            variant="low",
        )

    # Then only the exception type is surfaced, never the sensitive source text.
    assert str(captured.value) == "codex 모델 호출 네트워크 오류: ConnectError"
    assert _Credentials.access_token not in str(captured.value)


def test_deeply_nested_sse_json_is_ignored_by_both_transports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an SSE line deeper than the JSON decoder recursion limit.
    nested = "[" * 10000 + "0" + "]" * 10000
    response = _Response(200, ())
    response._lines = [f"data: {nested}"]
    _patch_transport(monkeypatch, response)

    # Then both plain and tool-enabled streams fail closed without raw exceptions.
    assert codex_oauth.call_codex_model(
        system_prompt="system",
        user_prompt="user",
        model=codex_oauth.DEFAULT_MODEL,
        variant="low",
    ) == ""
    text, calls = codex_oauth._stream_codex_round(body={}, headers={})
    assert text == ""
    assert calls == []


def test_tool_events_accumulate_incremental_arguments() -> None:
    # Given the three Responses events that form one function call.
    pending: dict[str, dict[str, Any]] = {}
    events = (
        {
            "type": "response.output_item.added",
            "item": {"type": "function_call", "id": "item-1", "call_id": "call-1", "name": "lookup"},
        },
        {"type": "response.function_call_arguments.delta", "item_id": "item-1", "delta": '{"q":'},
        {"type": "response.function_call_arguments.done", "item_id": "item-1", "arguments": '{"q":"olga"}'},
    )

    # When each event is folded into the facade accumulator.
    for event in events:
        codex_oauth._accumulate_tool_call_events(event, pending)

    # Then the completed call keeps its id, name, and final arguments.
    assert pending == {
        "item-1": {
            "call_id": "call-1",
            "name": "lookup",
            "arguments": '{"q":"olga"}',
        }
    }


def test_tool_loop_keeps_stream_monkeypatch_and_truncates_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given one tool call followed by a final text round.
    posted_bodies: list[dict[str, Any]] = []
    rounds = iter(
        (
            (
                "",
                [
                    {
                        "call_id": "call-1",
                        "name": "lookup",
                        "arguments": '{"q":"olga"}',
                        "item_id": "item-1",
                    }
                ],
            ),
            ("complete", []),
        )
    )

    def stream_round(*, body: dict[str, Any], headers: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
        del headers
        posted_bodies.append(body)
        return next(rounds)

    tool_events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(codex_oauth, "get_fresh_credentials", lambda: _Credentials())
    monkeypatch.setattr(codex_oauth, "_stream_codex_round", stream_round)

    # When the bounded tool loop dispatches a deliberately oversized result.
    result = codex_oauth.call_codex_model_with_tools(
        system_prompt="system",
        user_prompt="user",
        model=codex_oauth.DEFAULT_MODEL,
        variant="low",
        tools=[{"type": "function", "name": "lookup"}],
        tool_dispatch=lambda _name, _args: "x" * (codex_oauth.TOOL_RESULT_MAX_CHARS + 100),
        on_tool_event=lambda phase, info: tool_events.append((phase, info)),
    )

    # Then the patched facade seam drives both rounds and only bounded data is replayed.
    assert result == "complete"
    assert len(posted_bodies) == 2
    replay = posted_bodies[1]["input"]
    assert replay[-2]["type"] == "function_call"
    assert replay[-1]["type"] == "function_call_output"
    assert replay[-1]["output"].endswith(" …(truncated)")
    assert len(replay[-1]["output"]) < codex_oauth.TOOL_RESULT_MAX_CHARS + 20
    assert [phase for phase, _info in tool_events] == ["tool_call", "tool_result"]
