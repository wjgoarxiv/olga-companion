from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from olga_companion.runner import (
    detect_olga,
    execute_run,
    preview_run,
    run_capabilities,
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


def test_detect_without_env_is_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    # This dev machine has a real OLGA install the glob list now matches, so an
    # "OLGA-less machine" must be simulated with a glob that cannot match.
    monkeypatch.setattr(
        "olga_companion.runner.OLGA_EXE_GLOBS", [str(tmp_path / "nowhere" / "OLGA*" / "opi.exe")]
    )
    detection = detect_olga()
    assert detection["detected"] is False
    assert detection["searched"]
    caps = run_capabilities()
    assert caps["live_olga_run"]["enabled"] is False
    assert caps["live_olga_run"]["reason"].strip()


def test_detect_with_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    detection = detect_olga()
    assert detection["detected"] is True
    assert detection["source"] == "env:OLGA_EXE_PATH"
    assert run_capabilities()["live_olga_run"]["enabled"] is True


def test_run_capability_describes_availability_not_runtime_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))

    reason = run_capabilities()["live_olga_run"]["reason"]

    assert "availability only" in reason.lower()
    assert "verified on each run" in reason.lower()


@pytest.mark.parametrize("timeout_s", [0, True, 604_801])
def test_run_preview_rejects_unbounded_or_non_strict_timeouts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, timeout_s
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    case = _resolvable_case(tmp_path)

    with pytest.raises(ValueError, match="timeout_s must be an integer between 1 and 604800"):
        preview_run(str(case), timeout_s=timeout_s)


def test_run_preview_takes_a_run_limit_longer_than_a_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    case = _resolvable_case(tmp_path)

    preview = preview_run(str(case), timeout_s=3 * 86_400)

    assert preview["timeout_s"] == 3 * 86_400


def test_execute_requires_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr("olga_companion.runner.OLGA_EXE_GLOBS", [])
    with pytest.raises(ValueError, match="No OLGA executable"):
        execute_run(str(SIMPLE), approved=True)


def test_dash_leading_case_names_are_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    evil = tmp_path / "--evil.genkey"
    shutil.copy2(SIMPLE, evil)
    with pytest.raises(ValueError, match="must not start with"):
        execute_run(str(evil), approved=True)


def test_execute_requires_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    with pytest.raises(ValueError, match="explicit approval"):
        execute_run(str(SIMPLE), approved=False)


def test_execute_rejects_runtime_selection_drift_after_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    preview = preview_run(str(source))
    replacement = tmp_path / "replacement.py"
    replacement.write_text(FAKE_OLGA.read_text())
    monkeypatch.setenv("OLGA_EXE_PATH", str(replacement))

    with pytest.raises(ValueError, match="selection|preview|changed"):
        execute_run(
            str(source),
            approved=True,
            selection_id=preview["selection_id"],
        )


def test_execute_revalidates_candidate_id_before_staging_or_popen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion.config import sandbox_root

    source = _resolvable_case(tmp_path)
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    preview = preview_run(str(source))
    popen = Mock()
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    with pytest.raises(ValueError, match="candidate|runtime"):
        execute_run(
            str(source),
            approved=True,
            selection_id=preview["selection_id"],
            candidate_id="runtime_forged",
        )

    assert not (sandbox_root() / "runs").exists()
    popen.assert_not_called()


def test_execute_rejects_same_metadata_executable_replacement_before_staging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olga_companion.config import sandbox_root

    runtime = tmp_path / "runtime.py"
    runtime.write_bytes(FAKE_OLGA.read_bytes())
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    source = _resolvable_case(case_dir)
    monkeypatch.setenv("OLGA_EXE_PATH", str(runtime))
    preview = preview_run(str(source))
    original_stat = runtime.stat()
    payload = runtime.read_bytes()
    runtime.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
    os.utime(runtime, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    popen = Mock()
    monkeypatch.setattr("olga_companion.runner.subprocess.Popen", popen)

    with pytest.raises(ValueError, match="candidate|runtime|selection|preview"):
        execute_run(
            str(source),
            approved=True,
            selection_id=preview["selection_id"],
            candidate_id=preview["candidate_id"],
        )

    assert not (sandbox_root() / "runs").exists()
    popen.assert_not_called()
