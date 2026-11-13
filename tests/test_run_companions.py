from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from olga_companion.genkey_static import file_sha256
from olga_companion.runner import execute_run, run_status

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def _case(tmp_path: Path, restart: str) -> Path:
    case = tmp_path / "case.genkey"
    text = SIMPLE.read_text().replace('"./dummy_fluid.tab"', '"./fluid.tab"')
    case.write_text(f"{restart}\n{text}")
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    return case


def _wait(run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status = run_status(run_id)
        if status["state"] != "running":
            return status
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_relative_restart_with_spaces_is_staged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    restart_name = "restart state.rsw"
    source = _case(tmp_path, f'RESTART READFILE=ON, FILE="{restart_name}"')
    (tmp_path / restart_name).write_bytes(b"restart-data")
    before = file_sha256(source)

    started = execute_run(str(source), approved=True)
    run_dir = Path(started["run_dir"])

    assert started["restart_files"] == [restart_name]
    assert started["restart_missing"] == []
    assert (run_dir / restart_name).read_bytes() == b"restart-data"
    assert file_sha256(source) == before
    _wait(started["run_id"])


def test_missing_required_restart_blocks_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    source = _case(tmp_path, 'RESTART READFILE=ON, FILE="missing.rsw"')

    with pytest.raises(ValueError, match="RESTART.*missing.rsw"):
        execute_run(str(source), approved=True)


def test_restart_file_is_ignored_when_readfile_is_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    source = _case(tmp_path, 'RESTART READFILE=OFF, FILE="missing.rsw"')

    started = execute_run(str(source), approved=True)

    assert started["restart_files"] == []
    assert started["restart_missing"] == []
    _wait(started["run_id"])


def test_escaping_restart_is_rewritten_inside_run_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    work = tmp_path / "work"
    files = tmp_path / "files"
    work.mkdir()
    files.mkdir()
    (files / "state.rsw").write_bytes(b"restart-data")
    source = _case(work, 'RESTART READFILE=ON, FILE="../files/state.rsw"')

    started = execute_run(str(source), approved=True)
    run_dir = Path(started["run_dir"])
    executing_text = (run_dir / source.name).read_text()

    assert (run_dir / "state.rsw").read_bytes() == b"restart-data"
    assert "../files" not in executing_text
    assert 'FILE="./state.rsw"' in executing_text
    _wait(started["run_id"])
