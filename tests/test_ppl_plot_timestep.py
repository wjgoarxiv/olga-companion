"""A .ppl profile plot returns the profile at the asked time, or the last one.

Hyper-real round 4 (2026-11-11): results_plot on case.ppl rendered all five timesteps but
the receipt always carried MAIN_HOL_t000000.0.png, the initial state; asking for the end
time with timestep was refused as "A selected series export or PDF requires position."
"""
from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import result_plot_exports
from olga_companion.agent import result_artifact_tools, tool_read_tools, tools
from olga_companion.agent.tool_validation import PathBindings, ToolError, validate_tool_arguments
from olga_companion.genkey_static import CommandResult, file_sha256

STEPS = ("0.0", "900.1", "3600.1")


def _plot(tmp_path: Path, timestep: float | None) -> dict:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"stable profile")

    def fake_tool(_key, args, **_kwargs):
        out_dir = Path(args[args.index("--out-dir") + 1])
        for step in STEPS:
            (out_dir / f"MAIN_HOL_t{float(step):08.1f}.png").write_bytes(step.encode())
        return CommandResult(script="fast_ppl_plotter", args=args, exit_code=0, stdout="", stderr="", timed_out=False, elapsed_ms=1)

    return result_plot_exports.plot_result(
        str(source), ["HOL"], "MAIN", None,
        value_unit=None, time_unit=None, quantity_kind="point", range_spec=None,
        timestep=timestep,
        resolve_result=Path, hash_file=file_sha256,
        exports_root=lambda: tmp_path / "exports",
        require_tokens=lambda values, _kind: values,
        series_reader=None, publication_renderer=None,
        run_tool=fake_tool, result_scripts={}, plot_timeout_s=5,
    )


def test_the_last_profile_is_selected_by_default(tmp_path: Path) -> None:
    assert Path(_plot(tmp_path, None)["selected_plot"]).name == "MAIN_HOL_t003600.1.png"


def test_the_nearest_profile_to_a_timestep_is_selected(tmp_path: Path) -> None:
    assert Path(_plot(tmp_path, 1000)["selected_plot"]).name == "MAIN_HOL_t000900.1.png"


def test_the_receipt_carries_the_selected_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"stable profile")
    exports = tmp_path / "exports"
    first, last = (exports / "results" / "r" / "plots" / name for name in ("a_t0.png", "a_t3600.png"))
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    last.write_bytes(b"last")
    monkeypatch.setattr(result_artifact_tools.result_artifacts, "exports_root", lambda: exports)
    monkeypatch.setattr(result_artifact_tools.workspace, "context_generation", lambda: 1)
    seen: dict = {}

    def fake_plot(*args, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "plots": [str(first), str(last)], "selected_plot": str(last), "documents": []}

    monkeypatch.setattr(result_artifact_tools.results, "plot_result", fake_plot)
    paths = PathBindings(input_file=lambda v, _s: v, result_file=lambda _v: str(source), set_active_case=lambda _v: None)
    receipt = tool_read_tools.results_plot(
        {"path": "run:abc123/case.ppl", "variables": ["HOL"], "branch": "MAIN", "timestep": 3600}, paths
    )
    assert seen["timestep"] == 3600
    assert receipt["sha256"] == file_sha256(last)


def test_a_ppl_timestep_needs_no_position_but_a_tpl_view_still_does() -> None:
    schema = tools.TOOLS["results_plot"].parameters
    validate_tool_arguments(
        "results_plot", {"path": "run:abc123/case.ppl", "variables": ["HOL"], "branch": "MAIN", "timestep": 3600}, schema
    )
    with pytest.raises(ToolError, match="position"):
        validate_tool_arguments(
            "results_plot", {"path": "run:abc123/case.tpl", "variables": ["HOL"], "timestep": 3600}, schema
        )
