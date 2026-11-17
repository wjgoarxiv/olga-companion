"""An unexpected tool exception is logged with its tool and kind, never silently dropped.

Hyper-real round 3 (2026-11-11): results_plot failed twice in the installed app with
"도구 실행이 예기치 않게 실패했습니다" and nothing reached sidecar.log, so the cause could
not be traced. The same call worked from source.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from olga_companion.agent import runtime
from olga_companion.llm.protocol import StreamResult, ToolCall


class _Conversation:
    def add_user_message(self, text, images=None): ...
    def add_assistant_response(self, text, tool_calls=None, thought_signature=None): ...
    def add_tool_result(self, call_id, name, result): ...


class _Client:
    def __init__(self, script):
        self._script = list(script)

    def create_conversation(self, model=""):
        return _Conversation()

    async def stream_generate(self, **kwargs):
        return self._script.pop(0)


def test_an_unexpected_tool_exception_is_logged_without_secrets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def explode(_name, _args):
        raise RuntimeError("renderer broke Bearer tool-secret")

    monkeypatch.setattr(runtime.tools, "dispatch", explode)
    client = _Client(
        [
            StreamResult(tool_calls=[ToolCall(name="run_detect", args={}, call_id="c1")]),
            StreamResult(text="ok"),
        ]
    )

    async def collect():
        return [e async for e in runtime.run_turn(client, "plot it")]

    with caplog.at_level(logging.WARNING, logger=runtime.LOGGER_NAME):
        asyncio.run(collect())
    lines = [r.getMessage() for r in caplog.records if "tool_failed" in r.getMessage()]
    assert len(lines) == 1
    assert "name=run_detect" in lines[0]
    assert "kind=RuntimeError" in lines[0]
    assert "renderer broke" in lines[0]
    assert "tool-secret" not in lines[0]
