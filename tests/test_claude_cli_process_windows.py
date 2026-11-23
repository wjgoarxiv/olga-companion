"""Real Windows: the CLI run sits in a kill-on-close job, so cancel and stop_all end its children."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from olga_companion.llm import claude_cli_process as proc

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
FAKE = Path(__file__).parent / "fixtures" / "claude_cli" / "fake_claude.py"


def running(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def scenario(tmp_path: Path, **keys) -> dict[str, str]:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(keys), encoding="utf-8")
    return {**os.environ, "FAKE_CLAUDE_SCENARIO": str(path)}


def test_cancel_ends_the_grandchild_on_windows(tmp_path):
    pidfile = tmp_path / "gc.pid"
    run = proc.CliProcess([sys.executable, str(FAKE), "-p"], prompt="안녕", env=scenario(
        tmp_path, grandchild=str(pidfile), lines=[{"type": "a", "text": "한글 ·"}], sleep=60), cwd=tmp_path)

    async def go():
        got = []

        async def read():
            async for line in run.lines():
                got.append(line)

        task = asyncio.create_task(read())
        await asyncio.sleep(3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return got

    got = asyncio.run(go())
    assert json.loads(got[0])["text"] == "한글 ·"
    grandchild = int(pidfile.read_text())
    deadline = time.time() + 5
    while running(grandchild) and time.time() < deadline:
        time.sleep(0.2)
    assert not running(grandchild)
    assert not running(run.pid)


def test_stop_all_on_windows(tmp_path):
    pidfile = tmp_path / "gc.pid"
    run = proc.CliProcess([sys.executable, str(FAKE), "-p"], prompt="x",
                          env=scenario(tmp_path, grandchild=str(pidfile), sleep=60), cwd=tmp_path)
    run.start()
    deadline = time.time() + 10
    while not pidfile.exists() and time.time() < deadline:
        time.sleep(0.2)
    assert run._handle.in_job
    proc.stop_all()
    time.sleep(1)
    assert not running(int(pidfile.read_text()))
