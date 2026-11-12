from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from olga_companion.sweep_execution import SweepCaseState, SweepState, sweep_status

FAKE_OLGA = Path(__file__).parent / "fixtures" / "fake_olga" / "fake_olga.py"
FLUID_TAB = Path(__file__).parent / "fixtures" / "fluids" / "fluid.tab"
SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"


def _resolvable_case(tmp_path: Path) -> Path:
    case = tmp_path / "case.genkey"
    case.write_text(SIMPLE.read_text().replace('"./dummy_fluid.tab"', '"./fluid.tab"'))
    shutil.copy2(FLUID_TAB, tmp_path / "fluid.tab")
    return case


def _wait_for_sweep_final(sweep_id: str, timeout_s: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = sweep_status(sweep_id)
        if status["state"] != "running":
            return status
        time.sleep(0.2)
    raise AssertionError(f"sweep {sweep_id} did not finish within {timeout_s}s")


def _run_dirs() -> set[Path]:
    from olga_companion.config import sandbox_root

    runs_dir = sandbox_root() / "runs"
    return set(runs_dir.iterdir()) if runs_dir.exists() else set()


def _capture_error(call: Callable[[], Any], errors: list[Exception]) -> None:
    try:
        call()
    except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — record race loser
        errors.append(exc)


def _synthetic_sweep(
    tmp_path: Path,
    *,
    run_id: str | None = "run-1",
    started: bool = True,
) -> SweepState:
    case = SweepCaseState(
        index=0,
        path=tmp_path / "case.genkey",
        valid=True,
        validation_errors=[],
        params=[],
        source_sha256="a" * 64,
        companions=[],
        run_id=run_id,
    )
    return SweepState(
        sweep_id="synthetic-sweep",
        base=tmp_path / "base.genkey",
        strategy="oat",
        sweeps=["INTEGRATION.ENDTIME=3600"],
        timeout_s=30,
        cases=[case],
        output_dir=str(tmp_path),
        command={},
        detection={},
        plan_id="synthetic-plan",
        context_generation=0,
        created_monotonic=5.0,
        started_monotonic=10.0 if started else None,
    )
