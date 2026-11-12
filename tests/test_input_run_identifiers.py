"""Inputs accept the result ids the results inventory hands out ("run:<id>/case.out").

On 2026-11-10, right after a finished managed run, diagnose_out was given
"run:<id>/case.out" (the id form results_inventory lists) and failed with
"input file not found", so the run's convergence report was never read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import config, workspace
from olga_companion.agent import tools


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    root.mkdir()
    (sandbox / "runs" / "abc123").mkdir(parents=True)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(config, "sandbox_root", lambda: sandbox)
    return root, sandbox


def test_run_identifier_resolves_into_the_run_sandbox(roots: tuple[Path, Path]) -> None:
    _root, sandbox = roots
    out = sandbox / "runs" / "abc123" / "case.out"
    out.write_text("OLGA run ended\n", encoding="utf-8")

    assert workspace.resolve_input_file("run:abc123/case.out", {".out"}) == out.resolve()


def test_workspace_identifier_resolves_into_the_workspace(roots: tuple[Path, Path]) -> None:
    root, _sandbox = roots
    log = root / "case.out"
    log.write_text("OLGA run ended\n", encoding="utf-8")

    assert workspace.resolve_input_file("workspace:case.out", {".out"}) == log.resolve()


def test_run_identifier_cannot_climb_out_of_the_run_sandbox(roots: tuple[Path, Path]) -> None:
    _root, sandbox = roots
    (sandbox / "secret.out").write_text("x\n", encoding="utf-8")

    with pytest.raises(workspace.WorkspaceError):
        workspace.resolve_input_file("run:../secret.out", {".out"})


def test_diagnose_out_reads_a_run_identifier(roots: tuple[Path, Path]) -> None:
    _root, sandbox = roots
    (sandbox / "runs" / "abc123" / "case.out").write_text("OLGA run ended\n", encoding="utf-8")

    result = tools.dispatch("diagnose_out", {"path": "run:abc123/case.out"})

    assert "error" not in result
