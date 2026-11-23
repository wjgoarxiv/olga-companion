from __future__ import annotations

from pathlib import Path
from typing import Any


def indeterminate_solver_progress(
    ctx: Any,
    *,
    phase: str = "indeterminate",
    liveness: str = "indeterminate",
    out_name: str | None = None,
) -> dict[str, Any]:
    return {
        "parse_status": "indeterminate",
        "activity_status": "terminal" if phase == "terminal" else "unavailable",
        "observed_at": ctx._utc_now(),
        "file_timestamp": None,
        "age_seconds": None,
        "simulation_time_s": None,
        "step": None,
        "adaptive_total_steps": None,
        "step_size_s": None,
        "vendor_percent": None,
        "fraction": None,
        "phase": phase,
        "liveness": liveness,
        "files": {"out": out_name, "run_log": "run.log"},
        "evidence": {"timestep": "indeterminate", "vendor_percent": "indeterminate"},
    }


def managed_progress_paths(run_dir: Path, staged_case_name: str) -> tuple[Path, Path] | None:
    staged = Path(staged_case_name)
    if not staged_case_name or staged.name != staged_case_name or staged.name in {".", ".."}:
        return None
    out_name = f"{staged.stem}.out"
    if Path(out_name).name != out_name:
        return None
    return run_dir / out_name, run_dir / "run.log"


def solver_progress_for(
    ctx: Any,
    run_dir: Path,
    staged_case_name: str,
    *,
    phase: str,
    liveness: str,
) -> dict[str, Any]:
    paths = ctx._managed_progress_paths(run_dir, staged_case_name)
    if paths is None:
        progress = ctx._indeterminate_solver_progress(phase=phase, liveness=liveness)
    else:
        out_path, log_path = paths
        progress = ctx.diagnostics.monitor_snapshot(str(out_path), str(log_path))
        progress["phase"] = phase
        progress["liveness"] = liveness
    if phase == "terminal":
        progress["activity_status"] = "terminal"
    return progress
