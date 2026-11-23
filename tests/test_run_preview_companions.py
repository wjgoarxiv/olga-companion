from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from olga_companion import runner
from olga_runtime_test_support import _installed_release


# Owner report 2026-11-16: a .tab outside the case folder only failed after approval.
# The preview must say before approval which referenced files the run will not find.
def test_preview_lists_each_referenced_file_and_whether_it_will_be_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", opi=False)
    case_dir = tmp_path / "case"
    (case_dir / "fluids").mkdir(parents=True)
    (case_dir / "fluids" / "near.tab").write_text("PVTTABLE LABEL = A\n")
    case = case_dir / "case.genkey"
    case.write_text(
        'CASE LABEL=case\nFILES PVTFILE="fluids/near.tab"\nFILES PVTFILE="../elsewhere/far.tab"\nENDCASE\n'
    )
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe")])
    monkeypatch.setattr(runner, "_validate_case", lambda _path: {"valid": True, "command": {}})
    monkeypatch.setattr(
        runner, "ensure_broker", lambda: SimpleNamespace(to_dict=lambda: {"protocol": "test", "sha256": "b" * 64})
    )

    preview = runner.preview_run(str(case))

    found = {item["reference"]: item["found"] for item in preview["companions"]}
    assert found == {"fluids/near.tab": True, "../elsewhere/far.tab": False}
    assert preview["companions_missing"] == ["../elsewhere/far.tab"]
    assert preview["companions_network"] == []


# Security review B1/C1: a shared case pointing at \\host\share must not reach the network.
def test_preview_flags_network_references_as_not_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", opi=False)
    case = tmp_path / "case.genkey"
    case.write_text('CASE LABEL=case\nFILES PVTFILE="\\\\127.0.0.1\\nope\\x.tab"\nENDCASE\n')
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe")])
    monkeypatch.setattr(runner, "_validate_case", lambda _path: {"valid": True, "command": {}})
    monkeypatch.setattr(
        runner, "ensure_broker", lambda: SimpleNamespace(to_dict=lambda: {"protocol": "test", "sha256": "b" * 64})
    )

    preview = runner.preview_run(str(case))

    assert preview["companions_missing"] == ["\\\\127.0.0.1\\nope\\x.tab"]
    assert preview["companions_network"] == ["\\\\127.0.0.1\\nope\\x.tab"]
