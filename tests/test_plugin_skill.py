"""The plugin's skill is generated from the tools it actually exposes, and never drifts from them."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from olga_companion import headless_mcp

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugin" / "skills" / "olga-companion" / "SKILL.md"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_plugin_skill", ROOT / "scripts" / "gen_plugin_skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_native_tab(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OLGA_COMPANION_NATIVE_TAB", raising=False)


def test_the_committed_skill_matches_the_generator():
    assert SKILL.read_text(encoding="utf-8") == _generator().render()


def test_every_exposed_tool_is_listed_once():
    text = SKILL.read_text(encoding="utf-8")
    for tool in headless_mcp.tool_list():
        assert len(re.findall(rf"^\| `{tool['name']}` \|", text, flags=re.M)) == 1, tool["name"]


def test_every_tool_named_in_the_prose_exists():
    names = {tool["name"] for tool in headless_mcp.tool_list()}
    prefixes = {name.split("_")[0] for name in names}
    prose = _generator().HEADER
    mentioned = {word for word in re.findall(r"`([a-z]+_[a-z_]+)`", prose) if word.split("_")[0] in prefixes}
    assert mentioned and mentioned <= names


def test_a_new_tool_makes_the_skill_stale(monkeypatch: pytest.MonkeyPatch):
    real = headless_mcp.tool_list
    monkeypatch.setattr(headless_mcp, "tool_list", lambda: [*real(), {"name": "fake_tool", "description": "Fake.", "annotations": {"readOnlyHint": True}}])
    assert _generator().render() != SKILL.read_text(encoding="utf-8")


def test_the_skill_names_the_product_and_its_safety_rules():
    text = SKILL.read_text(encoding="utf-8")
    front = text.split("---")[1]
    assert re.search(r"^name: olga-companion$", front, flags=re.M)
    assert "claude" not in re.search(r"^name: .*$", front, flags=re.M).group(0).lower()
    assert "new file" in text and "permission" in text
    assert "Windows" in text
