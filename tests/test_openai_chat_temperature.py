"""openai-chat temperature is opt-in for third-party endpoints.

Anthropic's OpenAI-compatible endpoint rejects `temperature` for some models,
so the API-key client must not send it unless explicitly configured. The
Copilot path keeps today's 0.7 default.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from olga_companion.llm import api_key_connections as keys
from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient


def _serve_recording(recorded: list[dict]) -> tuple[ThreadingHTTPServer, int]:
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return None

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            recorded.append(json.loads(self.rfile.read(length)))
            payload = {"choices": [{"delta": {"content": "ok"}}]}
            body = f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    return server, server.server_address[1]


async def _run(client: OpenAIChatApiClient, **kwargs) -> None:
    conversation = client.create_conversation()
    conversation.add_user_message("hi")
    await client.stream_generate(
        conversation=conversation,
        model="claude-sonnet-5-5",
        system_instruction="sys",
        **kwargs,
    )


def _apikey_client(monkeypatch: pytest.MonkeyPatch, port: int) -> object:
    monkeypatch.setattr(
        keys,
        "_http_post",
        lambda url, headers, payload, timeout: httpx.Response(200),
    )
    saved = keys.save_connection(
        {
            "label": "Local",
            "protocol": "openai-chat",
            "base_url": f"http://127.0.0.1:{port}/v1",
            "model": "claude-sonnet-5-5",
            "key": "local-test-key",
        }
    )
    assert keys.verify_connection(saved["id"])["outcome"] == "verified"
    return keys.build_agent_client(saved["id"])


def test_apikey_client_body_has_no_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []
    server, port = _serve_recording(recorded)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _apikey_client(monkeypatch, port)
        asyncio.run(_run(client))
    finally:
        server.shutdown()
        server.server_close()

    assert len(recorded) == 1
    assert "temperature" not in recorded[0]


def test_explicit_generation_config_temperature_is_still_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []
    server, port = _serve_recording(recorded)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _apikey_client(monkeypatch, port)
        asyncio.run(_run(client, generation_config={"temperature": 0.2}))
    finally:
        server.shutdown()
        server.server_close()

    assert len(recorded) == 1
    assert recorded[0]["temperature"] == 0.2


def test_default_client_still_sends_0_7() -> None:
    recorded: list[dict] = []
    server, port = _serve_recording(recorded)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAIChatApiClient(
            base_url=f"http://127.0.0.1:{port}/v1", access_token="test-token"
        )
        asyncio.run(_run(client))
    finally:
        server.shutdown()
        server.server_close()

    assert len(recorded) == 1
    assert recorded[0]["temperature"] == 0.7
