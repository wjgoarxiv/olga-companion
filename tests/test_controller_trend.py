"""0.1.21 row 6 (PVT): the controller output CONTR trended by a PID loop can be charted.

The trend catalog line is `CONTR 'CONTROLLER:' 'PC' '(-)' 'Controller output'`; the variable list offers
it as "CONTROLLER - PC", and fetching that series must return OLGA's values. Fixture: the trend file of
an app-built loop case run in OLGA 2022.1.0 (setpoint above every pressure, gain +0.5, bias 0.3).
"""
from __future__ import annotations

from pathlib import Path

from olga_companion import results as R

FIX = Path(__file__).parent / "fixtures" / "results"
TPL = FIX / "controller_loop.tpl"


def test_the_controller_output_is_listed_with_its_loop_label(monkeypatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    R._LOAD_CACHE.clear()
    contr = [v for v in R.load_result(str(TPL))["variables"] if v["variable"] == "CONTR"]
    assert [v["position"] for v in contr] == ["CONTROLLER - PC"]


def test_the_controller_output_series_can_be_fetched_by_the_listed_position(monkeypatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    series = R.variable_series(str(TPL), "CONTR", "CONTROLLER - PC")
    assert series["values"][0] == 0.3
    assert series["values"][-1] == 0.0
    assert len(series["values"]) == len(series["time"]) == 61


def test_a_section_trend_still_resolves_as_before(monkeypatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    series = R.variable_series(str(TPL), "PT", "POSITION - POS_MAIN")
    assert len(series["values"]) == 61
