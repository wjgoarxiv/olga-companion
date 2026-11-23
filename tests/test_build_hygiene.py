"""No build-machine paths in the repository, and private token files are owner-only (security review C3, C10, A)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Assembled so this file does not match itself.
PERSONAL = re.compile("|".join(["Users[\\\\/]+" + "Woo" + "jin", "Dream" + "Machine"]), re.IGNORECASE)


# Local working folders that the public export drops; everything else tracked is published.
_NEVER_PUBLISHED = (".litopencode/", ".claude/", ".litclaude/", ".litmuse/", "plans/", "var/", "HANDOFF.md")


def _tracked_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    return [ROOT / name for name in listed.split("\0") if name and not name.startswith(_NEVER_PUBLISHED)]


def test_no_tracked_file_names_the_build_account() -> None:
    hits = []
    for path in _tracked_files():
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        text = path.read_bytes().decode("utf-8", "ignore")
        if PERSONAL.search(text):
            hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_cargo_config_carries_no_account_path() -> None:
    config = (ROOT / "src-tauri" / ".cargo" / "config.toml").read_text(encoding="utf-8")
    assert "rustflags" not in config and "Users" not in config


def test_tauri_build_remaps_cargo_home_at_build_time() -> None:
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["tauri:build"] == "node scripts/tauri-build.mjs"
    wrapper = (ROOT / "scripts" / "tauri-build.mjs").read_text(encoding="utf-8")
    assert "CARGO_HOME" in wrapper and "--remap-path-prefix=" in wrapper and "RUSTFLAGS" in wrapper
    # Toolkit bytecode carries absolute source paths (seen in a local PVT install).
    assert "'__pycache__'" in wrapper and "rmSync" in wrapper


def test_tauri_build_warns_when_cargo_config_rustflags_would_be_dropped() -> None:
    # CARGO_ENCODED_RUSTFLAGS outranks every config-file rustflags, so dropping them must not be silent.
    wrapper = (ROOT / "scripts" / "tauri-build.mjs").read_text(encoding="utf-8")
    assert "config.toml" in wrapper and "/rustflags/" in wrapper and "console.warn" in wrapper


def test_both_readmes_explain_how_to_tell_a_genuine_download() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")
    assert "## How to tell a genuine download" in english
    assert "## 진짜 설치 파일인지 확인하기" in korean
    for text in (english, korean):
        assert "github.com/wjgoarxiv/olga-companion/releases" in text
        assert "Get-FileHash" in text


def test_gitignore_covers_secret_file_kinds() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    # Not a blanket *.key: OLGA case inputs use that extension.
    for pattern in (".env", ".env.*", "*.pem", "*updater*.key"):
        assert pattern in ignore


@pytest.mark.parametrize(
    ("module_name", "file_attr", "call"),
    [
        ("olga_companion.llm.copilot_auth", "COPILOT_TOKENS_FILE", lambda m: m.save_tokens("g", {"token": "c"})),
        ("olga_companion.llm.openai_auth", "OPENAI_TOKENS_FILE", lambda m: m.save_tokens({"access_token": "a"})),
    ],
)
def test_oauth_token_files_get_owner_only_acl(
    module_name: str, file_attr: str, call, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    module = importlib.import_module(module_name)
    target = tmp_path / "tokens.json"
    monkeypatch.setattr(module, file_attr, target)
    hardened: list[Path] = []
    monkeypatch.setattr(module, "harden_private_path", lambda path, *, directory: hardened.append(path))
    call(module)
    assert hardened == [target]


def test_antigravity_token_file_gets_owner_only_acl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion.llm.antigravity import token

    target = tmp_path / "tokens.json"
    monkeypatch.setattr(token, "TOKENS_FILE", target)
    hardened: list[Path] = []
    monkeypatch.setattr(token, "harden_private_path", lambda path, *, directory: hardened.append(path))
    token.save_tokens(token.OAuthTokens.from_dict({"access_token": "a", "refresh_token": "r", "expires_at": "2026-01-01T00:00:00+00:00"}))
    assert hardened == [target]
