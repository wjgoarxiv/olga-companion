from __future__ import annotations

import os
import runpy
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "g009_narrative_sidecar.py"


def test_g009_qa_runtime_pins_the_fake_olga(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    scope = runpy.run_path(str(SCRIPT))

    scope["configure_qa_runtime"]()

    expected = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
    assert Path(os.environ["OLGA_EXE_PATH"]).resolve() == expected.resolve()
    assert os.environ["FAKE_OLGA_RESULTS"] == "1"


def test_g009_narrative_does_not_claim_terminal_after_poll_limit(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    scope = runpy.run_path(str(SCRIPT))
    message = scope["Message"]("tool_result", "{}", "run_patrol")

    result = scope["NarrativeClient"]()._run(
        message,
        {"terminal": False, "state": "running", "stop_reason": "poll_limit"},
    )

    assert "terminal까지 확인" not in result.text
    assert "terminal 상태를 확인하지 못했습니다" in result.text
