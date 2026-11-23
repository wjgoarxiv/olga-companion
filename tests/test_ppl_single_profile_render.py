"""L2: a .ppl profile export draws one figure, the step on screen, not one per timestep.

Each frame is a 600 dpi PNG, so a 500-step run drew 500 figures for one Save PNG and could
hit the plot timeout. The request now names the step and the plotter draws only that one.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from olga_companion import result_plot_exports
from olga_companion.genkey_static import CommandResult, file_sha256

SCRIPT = Path(__file__).resolve().parents[1] / "resources" / "olga-toolkit" / "scripts" / "fast_ppl_plotter.py"
STEPS = [float(i) * 10.0 for i in range(500)]


def _load_script():
    # Never leave a __pycache__ in the bundled toolkit (test_packaging_config forbids it).
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("fast_ppl_plotter_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


class _FakePlotter:
    def __init__(self, *_args, **_kwargs) -> None:
        self._all_timesteps = list(STEPS)

    def _resolve_timestep(self, timestep):
        return self._all_timesteps[int(np.argmin(np.abs(np.array(self._all_timesteps) - timestep)))]

    def list_timesteps(self):
        return list(self._all_timesteps)

    def get_profile(self, _var, _branch, timestep=None):
        index = -1 if timestep is None else self._all_timesteps.index(self._resolve_timestep(timestep))
        return np.array([0.0, 1.0]), np.array([index, index + 1.0])

    def get_all_profiles(self, _var, _branch):
        return {t: np.array([0.0, 1.0]) for t in self._all_timesteps}


def _run_script(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]) -> list[tuple]:
    module = _load_script()
    calls: list[tuple] = []
    monkeypatch.setattr(module, "FastPPLPlotter", _FakePlotter)
    monkeypatch.setattr(module, "_plot_profile", lambda pos, vals, var, br, ts, out: calls.append((ts, out, list(vals))))
    source = tmp_path / "case.ppl"
    source.write_bytes(b"profile")
    monkeypatch.setattr(sys, "argv", ["fast_ppl_plotter.py", str(source), "--branch", "MAIN", "--var", "HOL", "--out-dir", str(tmp_path), *extra])
    with pytest.raises(SystemExit) as stop:
        module.main()
    assert stop.value.code == 0
    return calls


def test_png_mode_draws_only_the_nearest_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _run_script(monkeypatch, tmp_path, ["--timestep", "1234", "--png"])
    assert len(calls) == 1
    timestep, out, values = calls[0]
    assert timestep == 1230.0
    assert Path(out).name == "MAIN_HOL_t001230.0.png"
    assert values == [123.0, 124.0]


def test_png_mode_without_a_step_draws_the_last(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _run_script(monkeypatch, tmp_path, ["--png"])
    assert [c[0] for c in calls] == [STEPS[-1]]


def test_png_mode_uses_the_all_timesteps_file_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    one = _run_script(monkeypatch, tmp_path, ["--timestep", "4990", "--png"])
    every = _run_script(monkeypatch, tmp_path, ["--all-timesteps"])
    assert len(every) == 500
    assert one[0][1] == every[-1][1]


def _plot(tmp_path: Path, timestep: float | None) -> list[str]:
    source = tmp_path / "case.ppl"
    source.write_bytes(b"stable profile")
    seen: list[str] = []

    def fake_tool(_key, args, **_kwargs):
        seen.extend(args)
        out_dir = Path(args[args.index("--out-dir") + 1])
        (out_dir / "MAIN_HOL_t000010.0.png").write_bytes(b"png")
        return CommandResult(script="fast_ppl_plotter", args=args, exit_code=0, stdout="", stderr="", timed_out=False, elapsed_ms=1)

    result = result_plot_exports.plot_result(
        str(source), ["HOL"], "MAIN", None,
        value_unit=None, time_unit=None, quantity_kind="point", range_spec=None,
        timestep=timestep,
        resolve_result=Path, hash_file=file_sha256,
        exports_root=lambda: tmp_path / "exports",
        require_tokens=lambda values, _kind: values,
        series_reader=None, publication_renderer=None,
        run_tool=fake_tool, result_scripts={}, plot_timeout_s=5,
    )
    assert Path(result["selected_plot"]).name == "MAIN_HOL_t000010.0.png"
    return seen


def test_the_export_asks_for_one_step(tmp_path: Path) -> None:
    args = _plot(tmp_path, 1234.0)
    assert "--all-timesteps" not in args
    assert "--png" in args
    assert args[args.index("--timestep") + 1] == "1234.0"


def test_the_export_without_a_step_asks_for_the_last_one(tmp_path: Path) -> None:
    args = _plot(tmp_path, None)
    assert "--all-timesteps" not in args
    assert "--png" in args
    assert "--timestep" not in args
