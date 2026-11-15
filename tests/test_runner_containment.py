from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from olga_companion import runner as runner_module
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


def _completed_popen() -> Mock:
    popen = Mock()
    popen.return_value.poll.return_value = 0
    popen.return_value.wait.return_value = 0
    return popen


def _runtime_copy_from_command(command: list[str]) -> Path:
    assert command[0] == sys.executable
    runtime_copy = Path(command[1])
    assert runtime_copy.name.startswith("approved-runtime")
    return runtime_copy
def test_direct_run_executes_approved_copy_when_original_mutates_in_case_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.py"
    approved_bytes = FAKE_OLGA.read_bytes()
    replacement_bytes = b"raise SystemExit('replacement spawned')\n"
    runtime.write_bytes(approved_bytes)
    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(runtime))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    preview = preview_run(str(source))

    def mutate_runtime(_path: Path) -> dict[str, Any]:
        runtime.write_bytes(replacement_bytes)
        return {"valid": True, "command": {}}

    popen = _completed_popen()
    monkeypatch.setattr("olga_companion.runner._validate_case", mutate_runtime)
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    started = execute_run(str(source), approved=True, selection_id=preview["selection_id"])

    spawned = popen.call_args.args[0]
    runtime_copy = _runtime_copy_from_command(spawned)
    assert runtime_copy.read_bytes() == approved_bytes
    assert replacement_bytes not in runtime_copy.read_bytes()
    assert started["command"] == spawned
    assert started["approved_command"] == preview["command"]
    assert started["execution_artifact"] == {
        "name": runtime_copy.name,
        "sha256": hashlib.sha256(approved_bytes).hexdigest(),
    }
    receipt = json.loads((Path(started["run_dir"]) / "run.json").read_text())
    assert receipt["runtime"]["approved_path"] == str(runtime)
    assert receipt["runtime"]["approved_sha256"] == hashlib.sha256(approved_bytes).hexdigest()
    assert receipt["execution_artifact"] == started["execution_artifact"]
    assert receipt["approved_command"] == preview["command"]
    assert receipt["command"] == spawned


def test_direct_run_fails_closed_when_original_mutates_during_runtime_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion.config import sandbox_root

    runtime = tmp_path / "runtime.py"
    prefix = FAKE_OLGA.read_bytes() + b"\n#"
    approved_bytes = prefix + (b"a" * (2 * 1024 * 1024))
    replacement_bytes = prefix + (b"b" * (2 * 1024 * 1024))
    runtime.write_bytes(approved_bytes)
    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(runtime))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    preview = preview_run(str(source))
    runs_dir = sandbox_root() / "runs"
    before = set(runs_dir.iterdir()) if runs_dir.exists() else set()
    real_read = os.read
    mutated = False

    def mutate_after_first_chunk(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = real_read(descriptor, size)
        if not mutated and chunk:
            mutated = True
            runtime.write_bytes(replacement_bytes)
        return chunk

    popen = _completed_popen()
    monkeypatch.setattr(runner_module.os, "read", mutate_after_first_chunk)
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    with pytest.raises(ValueError, match="runtime|content|changed|hash"):
        execute_run(str(source), approved=True, selection_id=preview["selection_id"])

    after = set(runs_dir.iterdir()) if runs_dir.exists() else set()
    assert mutated is True
    assert after == before
    popen.assert_not_called()


def test_direct_run_ignores_original_mutation_after_contained_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:

    runtime = tmp_path / "runtime.py"
    approved_bytes = FAKE_OLGA.read_bytes()
    runtime.write_bytes(approved_bytes)
    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(runtime))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    preview = preview_run(str(source))
    real_write_record = runner_module.write_run_record
    mutated = False

    def mutate_original_on_receipt(run_dir: Path, receipt: dict) -> None:
        nonlocal mutated
        if not mutated:
            mutated = True
            runtime.write_bytes(b"raise SystemExit('late replacement')\n")
        real_write_record(run_dir, receipt)

    popen = _completed_popen()
    monkeypatch.setattr(runner_module, "write_run_record", mutate_original_on_receipt)
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    execute_run(str(source), approved=True, selection_id=preview["selection_id"])

    runtime_copy = _runtime_copy_from_command(popen.call_args.args[0])
    assert mutated is True
    assert runtime_copy.read_bytes() == approved_bytes


def test_direct_run_rejects_corrupted_contained_runtime_before_spawn_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion.config import sandbox_root

    runtime = tmp_path / "runtime.py"
    runtime.write_bytes(FAKE_OLGA.read_bytes())
    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(runtime))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    preview = preview_run(str(source))
    runs_dir = sandbox_root() / "runs"
    before = set(runs_dir.iterdir()) if runs_dir.exists() else set()
    real_write_record = runner_module.write_run_record
    corrupted = False

    def corrupt_contained_copy(run_dir: Path, receipt: dict) -> None:
        nonlocal corrupted
        real_write_record(run_dir, receipt)
        artifact = receipt.get("execution_artifact")
        if not corrupted and isinstance(artifact, dict):
            (run_dir / artifact["name"]).write_bytes(b"corrupt")
            corrupted = True

    popen = _completed_popen()
    monkeypatch.setattr(runner_module, "write_run_record", corrupt_contained_copy)
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    with pytest.raises(ValueError, match="runtime|artifact|changed|hash"):
        execute_run(str(source), approved=True, selection_id=preview["selection_id"])

    after = set(runs_dir.iterdir()) if runs_dir.exists() else set()
    assert corrupted is True
    assert after == before
    popen.assert_not_called()


def test_direct_runtime_copy_preserves_executable_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.py"
    runtime.write_bytes(FAKE_OLGA.read_bytes())
    runtime.chmod(0o751)
    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(runtime))
    monkeypatch.setattr("olga_companion.runner._validate_case", lambda _path: {"valid": True, "command": {}})
    popen = _completed_popen()
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    started = execute_run(str(source), approved=True)

    runtime_copy = _runtime_copy_from_command(started["command"])
    assert stat.S_IMODE(runtime_copy.stat().st_mode) == 0o751
