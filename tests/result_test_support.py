from __future__ import annotations

from pathlib import Path

import pytest

import olga_companion.results as results_module

FIXTURES = Path(__file__).parent / "fixtures" / "results"
TPL = FIXTURES / "fixture.tpl"
PPL = FIXTURES / "fixture.ppl"


@pytest.fixture(autouse=True)
def exports_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Route result exports to temporary storage for every importing test module."""
    root = tmp_path / "exports"
    root.mkdir()
    monkeypatch.setattr(results_module, "exports_root", lambda: root)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIXTURES))
    return root
