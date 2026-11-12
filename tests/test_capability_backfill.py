"""Capability backfill — the toolkit capabilities a Claude Code session has that
the app now also exposes as agent tools: diff, opi parse, pipe geometry, parametric
sweep (dry-run planning), and create-and-save."""
import shutil
from pathlib import Path

import pytest

from olga_companion.agent import tools

SAMPLES = Path(__file__).parent / "fixtures" / "cases"

pytestmark = pytest.mark.skipif(not (SAMPLES / "simple_pipeline.genkey").exists(), reason="OLGA skill samples unavailable")


@pytest.fixture
def sample_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    for name in ("simple_pipeline.genkey", "second_pipeline.genkey"):
        shutil.copy2(SAMPLES / name, tmp_path / name)
    return tmp_path


def test_new_capability_tools_registered():
    for name in ("genkey_diff", "genkey_save", "opi_parse", "pipe_geometry", "parametric_sweep", "sweep_execute"):
        assert name in tools.TOOLS, name
    # parametric_sweep is a dry-run planner (generates the matrix, runs no sims) → not a side-effect gate.
    assert tools.TOOLS["parametric_sweep"].side_effect is False
    assert tools.TOOLS["sweep_execute"].side_effect is True


def test_genkey_diff_two_cases(sample_workspace: Path):
    out = tools.dispatch("genkey_diff", {"path_a": str(sample_workspace / "simple_pipeline.genkey"), "path_b": str(sample_workspace / "second_pipeline.genkey")})
    assert out["ok"] is True
    assert "diff" in out


def test_pipe_geometry_lists_pipes(sample_workspace: Path):
    out = tools.dispatch("pipe_geometry", {"path": str(sample_workspace / "simple_pipeline.genkey"), "flowpath": "FLOWPATH_1", "op": "list_pipes"})
    assert out["ok"] is True


def test_parametric_sweep_dry_run_generates_matrix(sample_workspace: Path):
    out = tools.dispatch("parametric_sweep", {"base": str(sample_workspace / "simple_pipeline.genkey"), "sweep": "INTEGRATION.ENDTIME=3600,7200,10800", "strategy": "oat"})
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["sweep_id"]
    assert isinstance(out["plan"], list) and len(out["plan"]) == 3  # three ENDTIME values → three cases, no sims run
