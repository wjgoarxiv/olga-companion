from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from olga_companion import config, runner as runner_module
from olga_companion.runner import (
    execute_run,
    preview_run,
    run_status,
)

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"
BROKEN = SAMPLE_ROOT / "intentionally_broken.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def _resolvable_case(tmp_path: Path, name: str = "case.genkey") -> Path:
    """SIMPLE with its PVTFILE reference satisfied: refs ./fluid.tab, copied beside."""
    case = tmp_path / name
    text = SIMPLE.read_text()
    case.write_text(text.replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    return case


def _wait_for_final_state(run_id: str, timeout_s: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = run_status(run_id)
        if status["state"] != "running":
            return status
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not reach a final state within {timeout_s}s")


def test_selection_id_binds_the_resolved_case_path_and_companions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first = _resolvable_case(tmp_path / "first")
    second = _resolvable_case(tmp_path / "second")
    (second.parent / "fluid.tab").write_text((second.parent / "fluid.tab").read_text() + "\n! changed\n")

    first_preview = preview_run(str(first))
    second_preview = preview_run(str(second))

    assert first_preview["selection_id"] != second_preview["selection_id"]


def test_selection_id_binds_workspace_context_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    generation = 4
    monkeypatch.setattr("olga_companion.workspace.context_identity", lambda: (tmp_path.resolve(), generation))
    preview = preview_run(str(source))
    generation = 5

    with pytest.raises(ValueError, match="selection|preview|context|changed"):
        execute_run(str(source), approved=True, selection_id=preview["selection_id"])
def test_corrupt_workspace_context_blocks_preview_and_cannot_resurrect_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:

    source = _resolvable_case(tmp_path)
    context_path = tmp_path / "workspace-context.json"
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setattr(config, "_workspace_context_path", lambda: context_path, raising=False)
    marker = tmp_path / "initialized"
    monkeypatch.setattr(config, "_workspace_context_marker_path", lambda: marker, raising=False)
    config.set_workspace_root(str(tmp_path))
    preview = preview_run(str(source))
    context_path.write_text('{"root":')

    with pytest.raises(config.WorkspaceContextError, match="malformed|context"):
        preview_run(str(source))
    with pytest.raises(config.WorkspaceContextError, match="malformed|context"):
        execute_run(str(source), approved=True, selection_id=preview["selection_id"])


def test_selection_id_also_binds_workspace_root_when_generation_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:

    first_root = tmp_path / "first-root"
    second_root = tmp_path / "second-root"
    first_root.mkdir()
    second_root.mkdir()
    source = _resolvable_case(first_root)
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setattr(config, "_workspace_context_path", lambda: tmp_path / "context.json", raising=False)
    monkeypatch.setattr(config, "_workspace_context_marker_path", lambda: tmp_path / "initialized", raising=False)
    config.set_workspace_root(str(first_root))
    preview = preview_run(str(source))
    config.set_workspace_root(str(second_root))

    with pytest.raises(ValueError, match="selection|preview|changed"):
        execute_run(str(source), approved=True, selection_id=preview["selection_id"])


def test_selection_id_boot_nonce_is_stable_in_process_and_changes_on_simulated_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:

    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    first = preview_run(str(source))
    repeated = preview_run(str(source))
    assert repeated["selection_id"] == first["selection_id"]

    monkeypatch.setattr(runner_module, "_SELECTION_BOOT_NONCE", "simulated-new-sidecar-boot", raising=False)
    restarted = preview_run(str(source))

    assert restarted["selection_id"] != first["selection_id"]
    with pytest.raises(ValueError, match="selection|preview|changed"):
        execute_run(str(source), approved=True, selection_id=first["selection_id"])


@pytest.mark.parametrize("substituted", ["source", "companion"])
def test_execute_rejects_copy_substitution_against_approved_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, substituted: str
) -> None:
    from olga_companion.config import sandbox_root

    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    source = _resolvable_case(tmp_path)
    preview = preview_run(str(source))
    runs_dir = sandbox_root() / "runs"
    before = set(runs_dir.iterdir()) if runs_dir.exists() else set()
    real_copy2 = shutil.copy2

    def substitute_copy(src: str | Path, dst: str | Path, *args, **kwargs):
        src_path = Path(src)
        dst_path = Path(dst)
        target = source if substituted == "source" else source.parent / "fluid.tab"
        if src_path.resolve() == target.resolve():
            if substituted == "source":
                dst_path.write_text(source.read_text() + "\n! substituted during copy\n")
            else:
                dst_path.write_bytes(b"substituted companion bytes")
            return str(dst_path)
        return real_copy2(src, dst, *args, **kwargs)

    popen = Mock()
    popen.return_value.poll.return_value = 0
    popen.return_value.wait.return_value = 0
    monkeypatch.setattr("olga_companion.runner.shutil.copy2", substitute_copy)
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda path: {"valid": True, "command": {}})
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    refusal: ValueError | None = None
    try:
        execute_run(
            str(source),
            approved=True,
            selection_id=preview["selection_id"],
        )
    except ValueError as exc:
        refusal = exc
    finally:
        after = set(runs_dir.iterdir()) if runs_dir.exists() else set()
        for unexpected in after - before:
            shutil.rmtree(unexpected, ignore_errors=True)

    assert refusal is not None
    assert "changed" in str(refusal).lower() or "manifest" in str(refusal).lower()
    popen.assert_not_called()
    assert after == before, "copy substitution refusal must remove its staged run directory"
