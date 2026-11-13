from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from olga_companion.genkey_static import file_sha256
from olga_companion.runner import (
    detect_olga,
    execute_run,
    cancel_run,
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


def test_execute_blocks_on_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    with pytest.raises(ValueError, match="[Vv]alidation"):
        execute_run(str(BROKEN), approved=True)


def test_override_run_is_never_reported_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    started = execute_run(str(BROKEN), approved=True, override=True)
    assert started["validation"]["valid"] is False
    assert started["override"] is True
    final = _wait_for_final_state(started["run_id"])
    assert final["exit_code"] == 0
    assert final["ok"] is False, "exit 0 must not read as ok when validation had errors"


def test_execute_happy_path_stays_in_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    source = _resolvable_case(tmp_path)
    before = file_sha256(source)

    started = execute_run(str(source), approved=True)
    run_dir = Path(started["run_dir"])
    assert tmp_path in run_dir.parents, "tests must stage runs in their per-test temporary sandbox"
    assert started["command"], "exact command argv must be part of the evidence"
    assert started["detection"]["exe"] == str(FAKE_OLGA)

    final = _wait_for_final_state(started["run_id"])
    assert final["state"] == "completed"
    assert final["ok"] is True
    assert final["timed_out"] is False
    assert "FAKE-OLGA finished" in final["log_tail"]
    assert final["detection"] == started["detection"]
    assert (run_dir / "case.out").exists()
    assert file_sha256(source) == before


def test_timeout_kills_the_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_SLEEP", "30")
    started = execute_run(str(_resolvable_case(tmp_path)), approved=True, timeout_s=1)
    final = _wait_for_final_state(started["run_id"])
    assert final["state"] == "timed_out"
    assert final["timed_out"] is True
    assert final["ok"] is False


def test_cancel_terminates_the_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_SLEEP", "30")
    started = execute_run(str(_resolvable_case(tmp_path)), approved=True)
    cancelled = cancel_run(started["run_id"])
    assert cancelled["state"] == "cancelled"
    final = _wait_for_final_state(started["run_id"])
    assert final["state"] == "cancelled"
    assert final["ok"] is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_cancel_terminates_the_direct_run_process_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child_pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_SLEEP", "30")
    monkeypatch.setenv("FAKE_OLGA_CHILD_PID_FILE", str(child_pid_file))
    started = execute_run(str(_resolvable_case(tmp_path)), approved=True)
    deadline = time.monotonic() + 5
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child_pid_file.exists(), "fake runtime did not publish its child pid"
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))

    cancel_run(started["run_id"])

    deadline = time.monotonic() + 5
    process_state = ""
    while time.monotonic() < deadline:
        try:
            process_state = Path(f"/proc/{child_pid}/stat").read_text(encoding="utf-8").split()[2]
        except (FileNotFoundError, IndexError):
            break
        if process_state == "Z":
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"direct-run child process {child_pid} survived cancellation in state {process_state}")


# ---------------------------------------------------------------- T3: engine-failure honesty

ABORT_LOG = Path(__file__).parent / "fixtures" / "out" / "olga_abort_run.log"


def test_engine_failure_markers_force_not_ok():
    """T3 license-probe finding: opi.exe can exit 0 while the OLGA engine aborts.
    The real captured abort log must be detected as a failure."""
    from olga_companion.runner import _log_indicates_failure

    abort_text = ABORT_LOG.read_text(errors="replace")
    assert _log_indicates_failure(abort_text) is True
    assert _log_indicates_failure("0 of 1 case(s) finished successfully\n1 case(s) failed") is True
    assert _log_indicates_failure("1 of 1 case(s) finished successfully\n0 case(s) failed") is False
    # A clean finish must NOT trip the markers.
    assert _log_indicates_failure("FAKE-OLGA starting\nFAKE-OLGA finished\n") is False


def test_batch_summary_failure_overrides_zero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_BATCH_FAIL", "1")

    started = execute_run(str(_resolvable_case(tmp_path)), approved=True)
    final = _wait_for_final_state(started["run_id"])

    assert final["exit_code"] == 0
    assert final["state"] == "failed"
    assert final["ok"] is False
    assert "case(s) failed" in final["log_tail"]


def test_final_run_elapsed_time_stops_increasing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    started = execute_run(str(_resolvable_case(tmp_path)), approved=True)
    final = _wait_for_final_state(started["run_id"])

    time.sleep(0.05)

    assert run_status(started["run_id"])["elapsed_ms"] == final["elapsed_ms"]


# ---------------------------------------------------------------- T2: detection layouts


def test_glob_list_covers_flat_and_windows_layouts() -> None:
    """OLGA 2022.x installs opi.exe at OLGA*/opi.exe (no bin/); packaged sidecar needs C:/ forms."""
    from olga_companion.runner import OLGA_EXE_GLOBS

    assert "/mnt/c/Program Files/Schlumberger/OLGA*/opi.exe" in OLGA_EXE_GLOBS
    assert any(g.startswith("C:/") for g in OLGA_EXE_GLOBS)


def test_detect_matches_flat_layout_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "Schlumberger" / "OLGA 2022.1.0" / "opi.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("stub")
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(
        "olga_companion.runner.OLGA_EXE_GLOBS", [str(tmp_path / "Schlumberger" / "OLGA*" / "opi.exe")]
    )
    detection = detect_olga()
    assert detection["detected"] is True
    assert detection["source"] == "install-glob"
    assert detection["exe"] == str(exe)


def test_build_command_uses_init_when_wslinterop_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion.runner import _build_command

    init_path = tmp_path / "init"
    init_path.write_text("bridge")
    monkeypatch.setattr("olga_companion.runner.WSL_INIT_PATH", init_path)
    monkeypatch.setattr("olga_companion.runner.WSL_INTEROP_PATH", tmp_path / "missing-wslinterop")

    exe = "/mnt/c/Program Files/Schlumberger/OLGA 2022.1.0/opi.exe"
    assert _build_command(exe, "case.genkey") == [str(init_path), exe, exe, "-f", "case.genkey"]
