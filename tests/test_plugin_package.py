"""The Claude Code plugin and its marketplace entry carry the app's version and run the app's engine."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
REPO = "https://github.com/wjgoarxiv/olga-companion"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_manifest_names_the_plugin_and_carries_the_app_version():
    manifest = _json(PLUGIN / ".claude-plugin" / "plugin.json")
    assert manifest["name"] == "olga-companion"
    assert manifest["version"] == VERSION
    assert manifest["description"] and manifest["author"]["name"]
    assert _json(ROOT / "src-tauri" / "tauri.conf.json")["version"] == VERSION


def test_the_mcp_server_runs_this_exact_release_from_the_public_repo():
    servers = _json(PLUGIN / ".claude-plugin" / "plugin.json")["mcpServers"]
    assert list(servers) == ["olga-companion"]
    server = servers["olga-companion"]
    assert server["command"] == "uvx"
    assert server["args"] == ["--from", f"olga-companion[results] @ git+{REPO}@v{VERSION}", "olga-companion-mcp"]


def test_the_marketplace_lists_the_plugin_folder():
    market = _json(ROOT / ".claude-plugin" / "marketplace.json")
    assert market["name"] and market["owner"]["name"]
    (entry,) = market["plugins"]
    assert entry["name"] == "olga-companion"
    assert entry["source"] == "./plugin"
    assert entry["version"] == VERSION
    assert entry["description"]


def test_the_version_bump_moves_the_plugin_too():
    bump = ROOT / ".litclaude" / "tmp" / "bump.mjs"
    if not bump.is_file():
        pytest.skip("the release scripts are not part of a public checkout")
    text = bump.read_text(encoding="utf-8")
    for name in ("plugin/.claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "@v${from}"):
        assert name in text


def test_the_public_export_keeps_the_plugin():
    export = ROOT / ".litclaude" / "tmp" / "dist" / "export.mjs"
    if not export.is_file():
        pytest.skip("the release scripts are not part of a public checkout")
    drop = re.search(r"const drop = \[(.*?)\]", export.read_text(encoding="utf-8")).group(1)
    names = set(re.findall(r"'([^']+)'", drop))
    assert not names & {"plugin", ".claude-plugin"}


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI validates the plugin")
@pytest.mark.parametrize("target", [PLUGIN, ROOT])
def test_claude_code_accepts_the_plugin_and_the_marketplace(target: Path):
    run = subprocess.run(["claude", "plugin", "validate", str(target)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
