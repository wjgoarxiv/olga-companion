"""R13a: an edit that removes a valve schedule says so on the approval card; a sweep lists repeated keys."""

from __future__ import annotations

from pathlib import Path

from olga_companion.case_spec import normalize_case_spec
from olga_companion.case_transaction_apply import apply_operation
from olga_companion.case_transaction_models import SetValveOpening
from olga_companion.sweep_parameters import ambiguous_sweep_parameters, discover_sweep_parameters

from test_casespec_v3 import _v3, _valve


def test_valve_edit_shows_the_schedule_it_removes() -> None:
    raw = _v3()
    raw["equipment"] = [_valve("V_1", schedule=[{"time_s": 0.0, "opening": 1.0}, {"time_s": 300.0, "opening": 0.0}])]
    spec = normalize_case_spec(raw)
    updated, diff = apply_operation(spec, SetValveOpening(op="set_valve_opening", label="V_1", opening=0.5))
    assert diff.before["schedule"] == [{"time_s": 0.0, "opening": 1.0}, {"time_s": 300.0, "opening": 0.0}]
    assert diff.after == {"opening": 0.5, "schedule": None}
    assert next(item for item in updated.equipment if item.label == "V_1").schedule is None


def test_valve_edit_without_schedule_keeps_the_plain_diff() -> None:
    raw = _v3()
    raw["equipment"] = [_valve("V_1")]
    _, diff = apply_operation(normalize_case_spec(raw), SetValveOpening(op="set_valve_opening", label="V_1", opening=0.5))
    assert diff.after == 0.5


def test_repeated_sweep_keys_are_listed_not_dropped_silently(tmp_path: Path) -> None:
    case = tmp_path / "two.genkey"
    case.write_text(
        "INTEGRATION ENDTIME=10 s\nPIPE LABEL=A, ROUGHNESS=1e-5 m\nPIPE LABEL=B, ROUGHNESS=2e-5 m\n", encoding="utf-8"
    )
    paths = {parameter.path for parameter in discover_sweep_parameters(case)}
    assert "INTEGRATION.ENDTIME" in paths and "PIPE.ROUGHNESS" not in paths
    assert "PIPE.ROUGHNESS" in ambiguous_sweep_parameters(case)


def test_m7_a_long_schedule_diff_is_not_silently_cut() -> None:
    from olga_companion.agent.case_transaction_tools import _bounded

    schedule = {"opening": 1.0, "schedule": [{"time_s": float(t), "opening": 1.0} for t in range(0, 300, 30)]}
    text = _bounded(schedule, 400)
    assert len(text) <= 400
    three = {"opening": 1.0, "schedule": [{"time_s": t, "opening": o} for t, o in ((0, 1), (299, 1), (300, 0))]}
    assert _bounded(three, 400).endswith("}")
    assert _bounded(schedule, 80).endswith("chars)")
