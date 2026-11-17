"""Reasoning models behind OpenAI-compatible servers (HD AIC) put a <think> block before the answer."""

from __future__ import annotations

from olga_companion.llm.think_filter import ThinkFilter


def _run(chunks: list[str]) -> tuple[str, str]:
    f = ThinkFilter()
    shown, thought = "", ""
    for chunk in chunks:
        visible, hidden = f.feed(chunk)
        shown += visible
        thought += hidden
    visible, hidden = f.flush()
    return shown + visible, thought + hidden


def test_a_leading_think_block_is_hidden_from_the_answer() -> None:
    assert _run(["<think>plan the reply</think>\n\nAnswer."]) == ("Answer.", "plan the reply")


def test_tags_split_across_chunks_are_still_found() -> None:
    assert _run(["<th", "ink>a", "b</thi", "nk>", "Hi"]) == ("Hi", "ab")


def test_leading_whitespace_before_the_block_is_allowed() -> None:
    assert _run(["\n  <think>x</think>ok"]) == ("ok", "x")


def test_text_without_a_block_passes_through_unchanged() -> None:
    assert _run(["Hel", "lo <think> later"]) == ("Hello <think> later", "")


def test_a_short_answer_that_looks_like_a_tag_start_is_not_lost() -> None:
    assert _run(["<t"]) == ("<t", "")


def test_an_unclosed_block_is_kept_as_thinking() -> None:
    assert _run(["<think>never closed"]) == ("", "never closed")


def test_the_chat_stream_shows_only_the_answer_and_routes_thinking(monkeypatch) -> None:
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient

    parts = ["<think>", "weigh it", "</think>\n", "Final."]

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return None

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in parts)
            body = (body + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tokens: list[str] = []
    thoughts: list[str] = []

    async def on_token(text: str) -> None:
        tokens.append(text)

    async def go():
        client = OpenAIChatApiClient(base_url=f"http://127.0.0.1:{server.server_address[1]}/v1", access_token="t")
        conversation = client.create_conversation()
        conversation.add_user_message("hi")
        return await client.stream_generate(
            conversation=conversation, model="m", system_instruction="sys",
            on_token=on_token, on_thinking=thoughts.append,
        )

    try:
        result = asyncio.run(go())
    finally:
        server.shutdown()
    assert result.text == "Final."
    assert "".join(tokens) == "Final."
    assert "".join(thoughts) == "weigh it"
