"""API-key openai-chat turns use the real adapter, runtime, and nested tool wire format."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from olga_companion.agent import runtime
from olga_companion.agent import tools
from olga_companion.llm.api_key_connections import build_agent_client
from olga_companion.llm.api_key_connections import save_connection
from olga_companion.llm.api_key_connections import verify_connection
from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient


def test_chat_convert_tools_accepts_flat_agent_specs() -> None:
    specs = tools.tool_specs()

    converted = OpenAIChatApiClient._convert_tools(specs)

    glossary = next(item for item in converted if item["function"]["name"] == "olga_glossary")
    assert glossary == {
        "type": "function",
        "function": {
            "name": "olga_glossary",
            "description": glossary["function"]["description"],
            "parameters": glossary["function"]["parameters"],
        },
    }
    assert glossary["function"]["parameters"]["type"] == "object"
    assert "properties" in glossary["function"]["parameters"]


def test_verified_apikey_chat_turn_rounds_a_read_only_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, object]] = []

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return None

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            recorded.append(json.loads(self.rfile.read(length)))
            if len(recorded) == 1:
                payload = {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_glossary_1",
                                        "type": "function",
                                        "function": {
                                            "name": "olga_glossary",
                                            "arguments": '{"term":"PT"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            else:
                payload = {"choices": [{"delta": {"content": "glossary says ready"}}]}
            body = f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        "olga_companion.llm.api_key_connections._http_post",
        lambda url, headers, payload, timeout: httpx.Response(200),
    )
    try:
        saved = save_connection(
            {
                "label": "Local",
                "protocol": "openai-chat",
                "base_url": f"http://127.0.0.1:{port}/v1",
                "model": "claude-sonnet-5-5",
                "key": "local-test-key",
            }
        )
        assert verify_connection(saved["id"])["outcome"] == "verified"
        client = build_agent_client(saved["id"])

        async def collect() -> list[runtime.AgentEvent]:
            return [event async for event in runtime.run_turn(client, "hi")]

        events = asyncio.run(collect())
    finally:
        server.shutdown()
        server.server_close()

    assert len(recorded) == 2
    first = recorded[0]
    tools_wire = first["tools"]
    assert isinstance(tools_wire, list)
    glossary = next(item for item in tools_wire if item["function"]["name"] == "olga_glossary")
    assert glossary["type"] == "function"
    assert set(glossary) == {"type", "function"}
    assert first["model"] == "claude-sonnet-5-5"
    follow = recorded[1]["messages"]
    assistant = next(item for item in follow if item.get("tool_calls"))
    tool_message = next(item for item in follow if item["role"] == "tool")
    assert assistant["tool_calls"][0]["id"] == "call_glossary_1"
    assert tool_message["tool_call_id"] == "call_glossary_1"
    assert [event.type for event in events if event.type in {"text", "done"}][-2:] == ["text", "done"]
    assert events[-2].data["text"] == "glossary says ready"
