"""0.1.20 row 15: Settings connects outside AI tools by writing only the app's own entry.

Every test runs on a temporary home folder; the owner's real config files are never read.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import ai_tool_connect, bridge_registry
from olga_companion.agent import session_token
from olga_companion.sidecar import app

CODEX_BEFORE = '''# my settings
model = "gpt-5"

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
'''
GEMINI_BEFORE = '{\n  "theme": "Dark",\n  "mcpServers": {\n    "other": { "command": "node", "args": ["x.js"] }\n  }\n}\n'


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(ai_tool_connect, "_home", lambda: fake)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(bridge_registry, "_path", lambda: tmp_path / "bridge-connections.json")
    monkeypatch.setattr(ai_tool_connect, "bridge_command", lambda: ("C:\\Program Files\\OLGA Companion\\olga-companion-sidecar.exe", ["--mcp"]))
    return fake


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def test_codex_connect_adds_only_our_table_and_remove_restores_the_file(home: Path) -> None:
    config = _write(home / ".codex" / "config.toml", CODEX_BEFORE)
    result = ai_tool_connect.connect("codex")
    assert result["state"] == "connected" and Path(result["backup"]).read_bytes() == CODEX_BEFORE.encode()
    text = config.read_text(encoding="utf-8")
    assert text.startswith(CODEX_BEFORE), "other entries are byte-identical"
    parsed = tomllib.loads(text)
    entry = parsed["mcp_servers"]["olga-companion"]
    assert entry["command"].endswith("olga-companion-sidecar.exe") and entry["args"] == ["--mcp"]
    assert bridge_registry.product_for(entry["env"]["OLGA_BRIDGE_SECRET"]) == "codex"
    assert parsed["mcp_servers"]["context7"] == tomllib.loads(CODEX_BEFORE)["mcp_servers"]["context7"]

    removed = ai_tool_connect.remove("codex")
    assert removed["state"] == "removed"
    assert config.read_bytes() == CODEX_BEFORE.encode()
    assert bridge_registry.product_for(entry["env"]["OLGA_BRIDGE_SECRET"]) is None


def test_codex_connect_twice_keeps_one_entry_and_rotates_the_secret(home: Path) -> None:
    config = _write(home / ".codex" / "config.toml", CODEX_BEFORE)
    ai_tool_connect.connect("codex")
    first = tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"]["olga-companion"]["env"]["OLGA_BRIDGE_SECRET"]
    ai_tool_connect.connect("codex")
    text = config.read_text(encoding="utf-8")
    assert text.count("[mcp_servers.olga-companion]") == 1
    second = tomllib.loads(text)["mcp_servers"]["olga-companion"]["env"]["OLGA_BRIDGE_SECRET"]
    assert first != second and bridge_registry.product_for(first) is None


def test_codex_home_without_a_config_file_gets_a_new_one(home: Path) -> None:
    result = ai_tool_connect.connect("codex")
    config = home / ".codex" / "config.toml"
    assert result["backup"] is None and "olga-companion" in tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"]
    ai_tool_connect.remove("codex")
    assert not config.exists(), "a file Connect created is removed again, not left empty"


def test_codex_home_env_is_respected(home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codexhome"))
    ai_tool_connect.connect("codex")
    assert (tmp_path / "codexhome" / "config.toml").is_file()
    assert not (home / ".codex").exists()


@pytest.mark.parametrize(
    ("product", "relative", "broken"),
    [("codex", ".codex/config.toml", "model = [unclosed\n"), ("gemini", ".gemini/settings.json", "{ not json")],
)
def test_a_file_that_does_not_parse_is_refused_and_left_alone(home: Path, product: str, relative: str, broken: str) -> None:
    path = _write(home / relative, broken)
    with pytest.raises(ai_tool_connect.ConnectError, match="could not be read"):
        ai_tool_connect.connect(product)
    assert path.read_text(encoding="utf-8") == broken
    assert not bridge_registry.connected(product)
    assert not list(path.parent.glob("*backup*"))


def test_an_entry_with_our_name_that_we_did_not_write_is_refused(home: Path) -> None:
    text = CODEX_BEFORE + '\n[mcp_servers.olga-companion]\ncommand = "something-else"\n'
    path = _write(home / ".codex" / "config.toml", text)
    with pytest.raises(ai_tool_connect.ConnectError, match="already has"):
        ai_tool_connect.connect("codex")
    assert path.read_text(encoding="utf-8") == text


def test_gemini_connect_keeps_other_entries_and_remove_restores_the_file(home: Path) -> None:
    path = _write(home / ".gemini" / "settings.json", GEMINI_BEFORE)
    result = ai_tool_connect.connect("gemini")
    assert Path(result["backup"]).read_bytes() == GEMINI_BEFORE.encode()
    data = json.loads(path.read_text(encoding="utf-8"))
    before = json.loads(GEMINI_BEFORE)
    assert data["theme"] == before["theme"] and data["mcpServers"]["other"] == before["mcpServers"]["other"]
    entry = data["mcpServers"]["olga-companion"]
    assert entry["args"] == ["--mcp"] and bridge_registry.product_for(entry["env"]["OLGA_BRIDGE_SECRET"]) == "gemini"
    ai_tool_connect.remove("gemini")
    assert path.read_bytes() == GEMINI_BEFORE.encode()


def test_gemini_remove_after_the_user_edited_the_file_removes_only_our_entry(home: Path) -> None:
    path = _write(home / ".gemini" / "settings.json", GEMINI_BEFORE)
    ai_tool_connect.connect("gemini")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["theme"] = "Light"
    path.write_text(json.dumps(data), encoding="utf-8")
    ai_tool_connect.remove("gemini")
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["theme"] == "Light" and "olga-companion" not in after["mcpServers"] and "other" in after["mcpServers"]


def test_claude_code_only_gets_commands_to_paste(home: Path) -> None:
    result = ai_tool_connect.connect("claude-code")
    assert result["state"] == "command"
    command = result["command"]
    assert command.startswith("claude mcp add --scope user --env OLGA_BRIDGE_SECRET=")
    assert command.endswith('--transport stdio olga-companion -- "C:\\Program Files\\OLGA Companion\\olga-companion-sidecar.exe" "--mcp"')
    assert "'" not in command, "single quotes do not survive cmd"
    secret = command.split("OLGA_BRIDGE_SECRET=", 1)[1].split(" ", 1)[0]
    assert bridge_registry.product_for(secret) == "claude-code"
    assert not (home / ".claude.json").exists() and not (home / ".claude").exists()
    removed = ai_tool_connect.remove("claude-code")
    assert removed["command"] == "claude mcp remove --scope user olga-companion"
    assert not bridge_registry.connected("claude-code")


def test_status_lists_each_tool_and_the_route_needs_the_session_token(home: Path) -> None:
    client = TestClient(app, base_url="http://127.0.0.1:8865", client=("127.0.0.1", 50000))
    assert client.get("/api/ai-tools").status_code == 401
    headers = {"X-Session-Token": session_token.boot_token()}
    listed = client.get("/api/ai-tools", headers=headers).json()["tools"]
    assert [tool["product"] for tool in listed] == ["claude-code", "codex", "gemini"]
    assert {tool["mode"] for tool in listed} == {"command", "file"}
    connected = client.post("/api/ai-tools/codex/connect", headers=headers).json()
    assert connected["state"] == "connected"
    assert next(tool for tool in client.get("/api/ai-tools", headers=headers).json()["tools"] if tool["product"] == "codex")["connected"] is True
    assert client.post("/api/ai-tools/unknown/connect", headers=headers).status_code == 400


@pytest.mark.parametrize("product", ["codex", "gemini"])
def test_connect_twice_then_remove_restores_the_first_original(home: Path, product: str) -> None:
    relative, before = (".codex/config.toml", CODEX_BEFORE) if product == "codex" else (".gemini/settings.json", GEMINI_BEFORE)
    path = _write(home / relative, before)
    ai_tool_connect.connect(product)
    ai_tool_connect.connect(product)
    ai_tool_connect.remove(product)
    assert path.read_bytes() == before.encode()


def test_a_crlf_file_is_kept_byte_exact(home: Path) -> None:
    before = CODEX_BEFORE.replace("\n", "\r\n").encode()
    path = home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_bytes(before)
    ai_tool_connect.connect("codex")
    written = path.read_bytes()
    assert written.startswith(before) and b"\r\r\n" not in written
    tomllib.loads(written.decode())
    ai_tool_connect.remove("codex")
    assert path.read_bytes() == before


def test_a_symlinked_config_stays_a_symlink(home: Path, tmp_path: Path) -> None:
    real = _write(tmp_path / "dotfiles" / "config.toml", CODEX_BEFORE)
    link = home / ".codex" / "config.toml"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    ai_tool_connect.connect("codex")
    assert link.is_symlink() and "olga-companion" in real.read_text(encoding="utf-8")
    ai_tool_connect.remove("codex")
    assert link.is_symlink() and real.read_bytes() == CODEX_BEFORE.encode()


def test_the_backup_keeps_the_original_permissions(home: Path) -> None:
    path = _write(home / ".codex" / "config.toml", CODEX_BEFORE)
    path.chmod(0o600)
    backup = Path(ai_tool_connect.connect("codex")["backup"])
    assert backup.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600


def test_the_registry_keeps_no_copy_of_the_users_file(home: Path) -> None:
    _write(home / ".codex" / "config.toml", CODEX_BEFORE)
    ai_tool_connect.connect("codex")
    assert "context7" not in bridge_registry._path().read_text(encoding="utf-8")
