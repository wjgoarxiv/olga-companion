"""Running the CLI: stdin prompt, UTF-8 line stream, caps, timeouts and whole-tree cleanup."""

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

FAKE = Path(__file__).parent / "fixtures" / "claude_cli" / "fake_claude.py"


def scenario(tmp_path: Path, **keys) -> dict[str, str]:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(keys), encoding="utf-8")
    return {**os.environ, "FAKE_CLAUDE_SCENARIO": str(path)}


async def collect(run: proc.CliProcess) -> list[str]:
    return [line async for line in run.lines()]


def start(tmp_path, env, prompt="hi", limits=None) -> proc.CliProcess:
    return proc.CliProcess([sys.executable, str(FAKE), "-p"], prompt=prompt, env=env, cwd=tmp_path,
                           limits=limits or proc.Limits())


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return True


def test_prompt_goes_on_stdin_and_lines_come_back_as_utf8(tmp_path):
    run = start(tmp_path, scenario(tmp_path, echo_prompt=True, lines=[{"type": "a", "text": "결과 안녕"}]),
                prompt="사례를 읽어 줘")
    lines = asyncio.run(collect(run))
    assert json.loads(lines[0])["text"] == "결과 안녕"
    assert json.loads(lines[1])["text"] == "사례를 읽어 줘"
    assert run.returncode == 0


def test_output_is_decoded_as_utf8_whatever_the_locale(tmp_path, monkeypatch):
    monkeypatch.setattr("locale.getpreferredencoding", lambda *a, **k: "cp949")
    run = start(tmp_path, scenario(tmp_path, lines=[{"t": "·한글"}], raw="\xff\xfe not utf8"))
    lines = asyncio.run(collect(run))
    assert json.loads(lines[0])["t"] == "·한글"
    assert "\ufffd" in lines[1]


def test_a_long_line_arrives_whole_and_an_oversized_one_is_refused(tmp_path):
    limits = proc.Limits(line_bytes=1_000_000)
    lines = asyncio.run(collect(start(tmp_path, scenario(tmp_path, big_line=600_000), limits=limits)))
    assert len(json.loads(lines[0])["text"]) == 600_000
    with pytest.raises(proc.CliProcessError) as err:
        asyncio.run(collect(start(tmp_path, scenario(tmp_path, big_line=1_200_000), limits=limits)))
    assert err.value.code == "output_too_large"


def test_total_output_cap(tmp_path):
    limits = proc.Limits(line_bytes=1_000_000, total_bytes=1_500_000)
    lines = [{"type": "x", "text": "y" * 400_000} for _ in range(5)]
    with pytest.raises(proc.CliProcessError) as err:
        asyncio.run(collect(start(tmp_path, scenario(tmp_path, lines=lines), limits=limits)))
    assert err.value.code == "output_too_large"


def test_no_first_event_times_out_and_kills_the_whole_tree(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    run = start(tmp_path, scenario(tmp_path, grandchild=str(pidfile), sleep=60), limits=proc.Limits(first_event_s=1.5))
    with pytest.raises(proc.CliProcessError) as err:
        asyncio.run(collect(run))
    assert err.value.code == "timeout"
    grandchild = int(pidfile.read_text())
    deadline = time.time() + 5
    while alive(grandchild) and time.time() < deadline:
        time.sleep(0.1)
    assert not alive(grandchild)
    assert not alive(run.pid)


def test_idle_timeout_after_some_output(tmp_path):
    run = start(tmp_path, scenario(tmp_path, lines=[{"type": "a"}], sleep=60), limits=proc.Limits(idle_s=1.0))
    with pytest.raises(proc.CliProcessError) as err:
        asyncio.run(collect(run))
    assert err.value.code == "timeout"


def test_cancelling_the_turn_kills_the_tree(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    run = start(tmp_path, scenario(tmp_path, grandchild=str(pidfile), lines=[{"type": "a"}], sleep=60))

    async def go():
        task = asyncio.create_task(collect(run))
        await asyncio.sleep(1.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    deadline = time.time() + 5
    grandchild = int(pidfile.read_text())
    while alive(grandchild) and time.time() < deadline:
        time.sleep(0.1)
    assert not alive(grandchild)


def test_stop_all_ends_every_running_cli(tmp_path):
    run = start(tmp_path, scenario(tmp_path, sleep=60))
    run.start()
    assert run in proc.active()
    proc.stop_all()
    run.wait(5)
    assert not alive(run.pid)
    assert run not in proc.active()


def test_app_shutdown_also_stops_cli_runs(monkeypatch):
    from olga_companion import runner

    called = []
    monkeypatch.setattr(proc, "stop_all", lambda: called.append(True))
    monkeypatch.setattr(runner.run_lifecycle, "shutdown_direct_runs", lambda context: None)
    runner.shutdown_direct_runs()
    assert called == [True]


def test_windows_launch_uses_the_kill_on_close_job_with_pipes(monkeypatch, tmp_path):
    seen = {}

    class Job:
        in_job = True
        pid = 4242
        returncode = None
        stdin = stdout = stderr = None

    def fake_launch(command, *, cwd, stdout, stdin=None, stderr=None, env=None):
        seen.update(command=command, stdout=stdout, stdin=stdin, stderr=stderr, env=env)
        return Job()

    monkeypatch.setattr(proc, "_windows", lambda: True)
    monkeypatch.setattr(proc.windows_native_launch, "launch_in_job", fake_launch)
    proc._spawn(["C:\\x\\claude.exe", "-p"], env={"A": "1"}, cwd=tmp_path)
    assert seen["stdin"] == seen["stdout"] == seen["stderr"] == subprocess.PIPE
    assert seen["env"] == {"A": "1"}
    assert seen["command"] == ["C:\\x\\claude.exe", "-p"]


def test_a_cmd_shim_is_started_as_one_quoted_cmd_line(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(proc, "_windows", lambda: True)
    monkeypatch.setattr(proc.windows_native_launch, "launch_in_job",
                        lambda command, **kw: seen.setdefault("command", command))
    shim = "C:\\Users\\홍 길동\\AppData\\Roaming\\npm\\claude.cmd"
    proc._spawn(["cmd.exe", "/d", "/s", "/c", shim, "-p", "--tools", ""], env={}, cwd=tmp_path)
    assert seen["command"] == f'cmd.exe /d /s /c ""{shim}" -p --tools """'


def test_without_a_job_the_tree_is_ended_with_taskkill(monkeypatch):
    calls = []

    class NoJob:
        in_job = False
        pid = 777

        def poll(self):
            return None

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(proc, "_windows", lambda: True)
    monkeypatch.setattr(proc.subprocess, "run", lambda argv, **kw: calls.append(argv))
    proc._kill_tree(NoJob())
    assert ["taskkill", "/T", "/F", "/PID", "777"] in calls
