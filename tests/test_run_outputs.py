from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from olga_companion.genkey_static import file_sha256
from olga_companion.runner import execute_run, run_status

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def test_terminal_status_inventories_generated_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_EXE_PATH", str(FAKE_OLGA))
    monkeypatch.setenv("FAKE_OLGA_RESULTS", "1")
    case = tmp_path / "case.genkey"
    case.write_text(SIMPLE.read_text().replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    started = execute_run(str(case), approved=True)

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        final = run_status(started["run_id"])
        if final["state"] != "running":
            break
        time.sleep(0.1)
    else:
        raise AssertionError("run did not finish")

    by_name = {item["name"]: item for item in final["outputs"]}
    assert set(by_name) == {"case.out", "case.ppl", "case.tpl"}
    for name, metadata in by_name.items():
        path = Path(metadata["path"])
        assert metadata["size"] == path.stat().st_size
        assert metadata["sha256"] == file_sha256(path)
        assert metadata["suffix"] == Path(name).suffix
    assert by_name["case.tpl"]["result_id"] == f"run:{started['run_id']}/case.tpl"
    assert by_name["case.ppl"]["result_id"] == f"run:{started['run_id']}/case.ppl"
    assert "result_id" not in by_name["case.out"]
