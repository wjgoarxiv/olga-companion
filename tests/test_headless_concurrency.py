"""A slow tool call must not block ping, a cancel, or any other call behind it (review 2026-11-27)."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from olga_companion import headless_mcp

WAIT_S = 5


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ws").mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))


class _Lines:
    """A stdout that hands each complete line to a queue as soon as it is written."""

    def __init__(self) -> None:
        self.replies: queue.Queue[dict[str, Any]] = queue.Queue()
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.replies.put(json.loads(line))
        return len(text)

    def flush(self) -> None:
        pass


class _Server:
    def __init__(self, stdout: Any = None) -> None:
        read_fd, write_fd = os.pipe()
        self._stdin = os.fdopen(read_fd, "r", encoding="utf-8")
        self._feed = os.fdopen(write_fd, "w", encoding="utf-8")
        self.stdout = stdout or _Lines()
        self._thread = threading.Thread(target=headless_mcp.serve, args=(self._stdin, self.stdout), daemon=True)
        self._thread.start()

    def send(self, message: dict[str, Any]) -> None:
        self._feed.write(json.dumps(message) + "\n")
        self._feed.flush()

    def reply(self) -> dict[str, Any]:
        return self.stdout.replies.get(timeout=WAIT_S)

    def close(self) -> None:
        self._feed.close()
        self._thread.join(timeout=WAIT_S)
        assert not self._thread.is_alive(), "serve() did not return after stdin closed"


def _tool_call(request_id: int, name: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": {}}}


@pytest.fixture
def slow_tool(monkeypatch: pytest.MonkeyPatch):
    """`slow` blocks until released; any other tool answers at once with its own name."""
    release = threading.Event()
    started = threading.Event()

    def fake_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "slow":
            started.set()
            release.wait(timeout=30)
        return {"content": [{"type": "text", "text": name}], "isError": False}

    monkeypatch.setattr(headless_mcp, "call", fake_call)
    yield release, started
    release.set()


def test_ping_and_cancel_are_answered_while_a_tool_call_runs(slow_tool):
    release, started = slow_tool
    server = _Server()
    try:
        server.send(_tool_call(1, "slow"))
        assert started.wait(WAIT_S)
        server.send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        server.send(_tool_call(3, "run_cancel"))
        early = [server.reply(), server.reply()]
        assert {reply["id"] for reply in early} == {2, 3}
        assert next(r for r in early if r["id"] == 2)["result"] == {}
        assert next(r for r in early if r["id"] == 3)["result"]["content"][0]["text"] == "run_cancel"
        release.set()
        assert server.reply()["id"] == 1
    finally:
        release.set()
        server.close()


def test_a_call_cancelled_before_it_starts_is_not_run_or_answered(slow_tool, monkeypatch: pytest.MonkeyPatch):
    release, started = slow_tool
    monkeypatch.setattr(headless_mcp, "TOOL_WORKERS", 1)
    server = _Server()
    try:
        server.send(_tool_call(1, "slow"))
        assert started.wait(WAIT_S)
        server.send(_tool_call(2, "olga_glossary"))  # queued behind the slow call on the only worker
        server.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}})
        server.send({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        assert server.reply()["id"] == 3
        release.set()
        assert server.reply()["id"] == 1
    finally:
        release.set()
        server.close()
    assert server.stdout.replies.empty(), "a cancelled request must get no reply"


@pytest.mark.parametrize("stop", ["run_cancel", "sweep_cancel"])
def test_a_stop_is_answered_while_every_worker_is_busy(slow_tool, monkeypatch: pytest.MonkeyPatch, stop: str):
    # Review of the fix: four long calls filled the four workers and a run_cancel queued behind them.
    release, started = slow_tool
    monkeypatch.setattr(headless_mcp, "TOOL_WORKERS", 1)
    server = _Server()
    try:
        server.send(_tool_call(1, "slow"))
        assert started.wait(WAIT_S)
        server.send(_tool_call(2, stop))
        answer = server.reply()
        assert answer["id"] == 2 and answer["result"]["content"][0]["text"] == stop
        release.set()
        assert server.reply()["id"] == 1
    finally:
        release.set()
        server.close()


def test_an_id_that_cannot_key_a_call_is_answered_and_the_server_keeps_serving(slow_tool):
    # Review of the fix: a list id raised TypeError in the pending map and ended serve().
    server = _Server()
    try:
        server.send({"jsonrpc": "2.0", "id": [7], "method": "tools/call", "params": {"name": "olga_glossary", "arguments": {}}})
        server.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": {"x": 1}}})
        server.send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        replies = [server.reply(), server.reply()]
        assert [7] in [reply["id"] for reply in replies]
        assert next(reply for reply in replies if reply["id"] == 2)["result"] == {}
    finally:
        server.close()


def test_a_failure_inside_a_worker_still_answers_that_request(monkeypatch: pytest.MonkeyPatch):
    # Review of the fix: an exception in a worker stayed in its Future and the request was never answered.
    real = headless_mcp.handle

    def broken(message: dict[str, Any]) -> dict[str, Any] | None:
        if message.get("method") == "tools/call":
            raise RuntimeError("boom")
        return real(message)

    monkeypatch.setattr(headless_mcp, "handle", broken)
    server = _Server()
    try:
        server.send(_tool_call(1, "olga_glossary"))
        answer = server.reply()
        assert answer["id"] == 1 and answer["error"]["code"] == -32603
        assert "boom" not in json.dumps(answer)
        server.send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert server.reply()["id"] == 2
    finally:
        server.close()


def test_every_reply_is_one_whole_line_when_calls_finish_together(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        headless_mcp, "call", lambda name, arguments: {"content": [{"type": "text", "text": "x" * 20000}], "isError": False}
    )
    server = _Server()
    try:
        for request_id in range(1, 21):
            server.send(_tool_call(request_id, "olga_glossary"))
        replies = [server.reply() for _ in range(20)]
    finally:
        server.close()
    assert sorted(reply["id"] for reply in replies) == list(range(1, 21))


class _Pieces:
    """A stdout like a pipe that takes a long write in pieces, with a thread switch between them."""

    def __init__(self) -> None:
        self.text = ""

    def write(self, text: str) -> int:
        for start in range(0, len(text), 1000):
            self.text += text[start : start + 1000]
            time.sleep(0.001)
        return len(text)

    def flush(self) -> None:
        pass


def test_replies_stay_whole_when_stdout_takes_each_one_in_pieces(monkeypatch: pytest.MonkeyPatch):
    # Without write_lock the pieces of two replies interleave and a line is no longer one JSON object.
    monkeypatch.setattr(
        headless_mcp, "call", lambda name, arguments: {"content": [{"type": "text", "text": "x" * 20000}], "isError": False}
    )
    stdout = _Pieces()
    server = _Server(stdout)
    try:
        for request_id in range(1, 21):
            server.send(_tool_call(request_id, "olga_glossary"))
        deadline = time.monotonic() + WAIT_S
        while stdout.text.count("\n") < 20 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        server.close()
    lines = stdout.text.splitlines()
    assert len(lines) == 20
    assert sorted(json.loads(line)["id"] for line in lines) == list(range(1, 21))
