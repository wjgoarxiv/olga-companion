"""Recorded and synthetic Claude Code stream fixtures stay parseable, redacted and replayable."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

DIR = Path(__file__).parent / "fixtures" / "claude_cli"
FIXTURES = sorted(DIR.glob("*.jsonl"))
GARBAGE = {"synthetic_garbage.jsonl", "synthetic_garbage_mixed.jsonl"}
# `user` is the placeholder the fixture generator writes in place of the real account name.
LEAKS = [re.compile(r"@"), re.compile(r"sk-"), re.compile(r"[A-Za-z]:(\\\\)+Users(\\\\)+(?!user\\)\w", re.I),
         re.compile(r"/(home|Users)/(?!user/)\w")]


def _leaks(text: str) -> list[str]:
    return [pattern.pattern for pattern in LEAKS if pattern.search(text)]


def test_every_fixture_is_listed_in_the_readme_as_captured_or_synthetic():
    readme = (DIR / "README.md").read_text(encoding="utf-8")
    assert FIXTURES
    for path in FIXTURES:
        synthetic = path.name.startswith("synthetic_")
        key = "`synthetic_*.jsonl`" if synthetic else f"`{path.name}`"
        line = next(row for row in readme.splitlines() if key in row)
        assert ("synthetic" if synthetic else "captured") in line.lower(), path.name


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_lines_are_json_except_the_deliberate_garbage(path):
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            parsed.append(None)
    if path.name in GARBAGE:
        assert None in parsed
    else:
        assert None not in parsed
        assert parsed[0]["type"] == "system" and parsed[0]["subtype"] == "init"
        assert parsed[-1]["type"] == "result"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixtures_hold_no_email_key_or_user_path(path):
    assert _leaks(path.read_text(encoding="utf-8")) == []


def test_the_redaction_check_catches_a_seeded_user_path():
    seeded = json.dumps({"type": "system", "cwd": "C:\\Users\\someone\\Desktop"})
    assert _leaks(seeded)
    assert _leaks('{"cwd": "/home/someone/x"}')
    assert _leaks('{"email": "a@b.c"}')


def test_fake_claude_replays_a_fixture(tmp_path):
    scenario = tmp_path / "s.json"
    capture = tmp_path / "capture.json"
    scenario.write_text(json.dumps({"replay": str(DIR / "happy.jsonl"), "capture": str(capture)}), encoding="utf-8")
    run = subprocess.run([sys.executable, str(DIR / "fake_claude.py"), "-p", "--output-format", "stream-json"],
                         input="hello", capture_output=True, text=True, encoding="utf-8", timeout=30,
                         env={"FAKE_CLAUDE_SCENARIO": str(scenario), "PATH": ""})
    assert run.returncode == 0
    assert run.stdout.splitlines() == (DIR / "happy.jsonl").read_text(encoding="utf-8").splitlines()
    seen = json.loads(capture.read_text(encoding="utf-8"))
    assert seen["stdin"] == "hello" and "-p" in seen["argv"]
