"""The local CLI provider is documented for users: what it does, every failure code, safety, network."""

from __future__ import annotations

import re
from pathlib import Path

from olga_companion.llm import claude_cli_status, claude_cli_stream

ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"missing section: {heading}"
    return match.group(1)


def test_readme_has_the_local_cli_section_after_the_bridge():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", readme, re.M)
    assert headings.index("Local CLI provider") == headings.index("AI tools bridge") + 1
    section = _section(readme, "Local CLI provider")
    for phrase in ("never sees", "`claude`", "Check", "WSL"):
        assert phrase in section, phrase


def test_readme_names_every_failure_and_discovery_code():
    section = _section((ROOT / "README.md").read_text(encoding="utf-8"), "Local CLI provider")
    codes = [c for c in claude_cli_stream.CODES] + [c for c in claude_cli_status.DIAGNOSES if c != "ok"]
    missing = [code for code in codes if f"`{code}`" not in section]
    assert not missing, missing


def test_readme_does_not_claim_endorsement_or_a_closed_plugin_risk():
    section = _section((ROOT / "README.md").read_text(encoding="utf-8"), "Local CLI provider").lower()
    for claim in ("endorsed", "official anthropic", "approved by anthropic", "partnership"):
        assert claim not in section, claim
    assert "plugin" in section


def test_safety_gates_and_network_docs_cover_the_cli():
    gates = (ROOT / "docs" / "SAFETY_GATES.md").read_text(encoding="utf-8")
    bullet = next((line for line in gates.splitlines() if line.startswith("- ") and "local CLI" in line), "")
    for phrase in ("secret", "built-in tools", "approval", "plugin"):
        assert phrase in bullet, phrase
    network = (ROOT / "docs" / "NETWORK.md").read_text(encoding="utf-8")
    assert re.search(r"local CLI.*proxy|proxy.*local CLI", network, re.S | re.I)


def test_korean_readme_has_the_local_cli_section_with_every_code():
    readme = (ROOT / "README.ko.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", readme, re.M)
    assert headings.index("로컬 CLI 연결") == headings.index("AI 도구 연결") + 1
    section = _section(readme, "로컬 CLI 연결")
    for phrase in ("이 PC의 로컬 CLI", "AI 공급자", "보지 않습니다", "`claude`", "확인", "다시 찾기", "WSL", "플러그인"):
        assert phrase in section, phrase
    codes = [c for c in claude_cli_stream.CODES] + [c for c in claude_cli_status.DIAGNOSES if c != "ok"]
    missing = [code for code in codes if f"`{code}`" not in section]
    assert not missing, missing
    for claim in ("공식 인증", "제휴", "승인한"):
        assert claim not in section, claim
