"""Both READMEs explain how to use OLGA Companion as a Claude Code plugin, right after the local CLI section."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKET = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
PLUGIN = MARKET["plugins"][0]["name"]
COMMANDS = (
    "claude plugin marketplace add wjgoarxiv/olga-companion",
    f"claude plugin install {PLUGIN}@{MARKET['name']}",
    "claude --plugin-dir ./plugin",
    "uv",
)
CASES = [
    ("README.md", "Use without the app (Claude Code plugin)", "Local CLI provider",
     ("permission", "new file", "never overwritten", "Windows", "same engine")),
    ("README.ko.md", "앱 없이 쓰기 (Claude Code 플러그인)", "로컬 CLI 연결",
     ("권한", "새 파일", "덮어쓰지", "Windows", "같은 엔진")),
]


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"missing section: {heading}"
    return match.group(1)


@pytest.mark.parametrize(("name", "heading", "after", "phrases"), CASES)
def test_the_plugin_section_follows_the_local_cli_section(name: str, heading: str, after: str, phrases: tuple[str, ...]):
    text = (ROOT / name).read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings.index(heading) == headings.index(after) + 1
    section = _section(text, heading)
    for command in COMMANDS:
        assert command in section, command
    for phrase in phrases:
        assert phrase in section, phrase
