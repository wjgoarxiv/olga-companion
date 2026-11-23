"""0.1.21 row 4: a case with a PID loop offers its setpoint, gain, integral and derivative time in the
edit table; each edit goes through the same reviewed plan and approved publish as any other row."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_case_edit_routes import _install, _plan, _publish, _row, _rows, ws  # noqa: F401

from olga_companion import case_compiler, case_edit_table
from olga_companion.case_lint import keyword_coverage
from olga_companion.case_spec import normalize_case_spec
from olga_companion.case_spec_recovery import recover_case_spec

LOOP = {
    "kind": "pid", "label": "PC", "valve": "ESD",
    "measure": {"variable": "PT", "flowpath": "MAIN", "pipe": "UPSTREAM", "section": 5},
    "setpoint": 2_000_000.0, "gain": 0.5, "integral_s": 60.0, "derivative_s": 0.0,
    "bias": 0.5, "norm_range": 100_000.0, "stroke_s": 10.0,
}


def _loop_case(ws: Path, **loop_changes) -> Path:  # noqa: F811
    """The valve example with its schedule removed and one pressure loop on the valve."""
    source = _install(ws, "valve-shut-in")
    raw = recover_case_spec(source).model_dump(mode="json", by_alias=True, exclude_none=True)
    raw.pop("meta", None)
    for valve in raw["equipment"]:
        valve.pop("schedule", None)
    raw["controllers"] = [{**LOOP, **loop_changes}]
    case = source.with_name("loop_case.genkey")
    case.write_bytes(case_compiler.render_case_spec(normalize_case_spec(raw)))
    return case


def test_a_loop_case_offers_its_four_tuning_values(ws: Path) -> None:  # noqa: F811
    rows = _rows(_loop_case(ws))
    expected = {"setpoint": (2_000_000.0, "Pa"), "gain": (0.5, ""), "integral_s": (60.0, "s"), "derivative_s": (0.0, "s")}
    for field, (value, unit) in expected.items():
        row = _row(rows, f"controllers.PC.{field}")
        assert (row["target"], row["field"], row["value"], row["unit"]) == ("PC", field, value, unit)
        assert row["op"] == {"op": "set_controller_value", "label": "PC"}


def test_a_flow_loop_setpoint_is_in_kg_per_s(ws: Path) -> None:  # noqa: F811
    measure = {"variable": "GT", "flowpath": "MAIN", "pipe": "UPSTREAM", "section": 5}
    rows = _rows(_loop_case(ws, measure=measure, setpoint=3.0, norm_range=1.0))
    assert _row(rows, "controllers.PC.setpoint")["unit"] == "kg/s"


def test_a_case_without_a_loop_offers_no_loop_rows(ws: Path) -> None:  # noqa: F811
    rows = _rows(_install(ws, "valve-shut-in"))
    assert not [row for row in rows["rows"] if row["id"].startswith("controllers.")]


def test_a_setpoint_edit_is_reviewed_and_published_as_a_new_copy(ws: Path) -> None:  # noqa: F811
    case = _loop_case(ws)
    before = case.read_bytes()
    plan = _plan(_rows(case), [{"op": "set_controller_value", "label": "PC", "setpoint": 2_500_000.0}]).json()

    assert plan["publishable"] is True, plan
    assert plan["semantic_diff"][0]["path"] == "controllers.PC.setpoint"
    assert float(plan["semantic_diff"][0]["before"]) == 2_000_000.0
    assert float(plan["semantic_diff"][0]["after"]) == 2_500_000.0
    assert case.read_bytes() == before, "planning must not touch the case"
    assert _publish(plan).status_code == 200
    copy = ws / plan["destination_rel"]
    assert "SETPOINT=(2500000)" in copy.read_text(encoding="utf-8")
    assert case.read_bytes() == before


def test_a_publish_without_approval_writes_nothing(ws: Path) -> None:  # noqa: F811
    case = _loop_case(ws)
    plan = _plan(_rows(case), [{"op": "set_controller_value", "label": "PC", "gain": 0.8}]).json()
    assert plan["publishable"] is True, plan
    response = _publish(plan, approved=False)
    assert response.status_code != 200
    assert not (ws / plan["destination_rel"]).exists()


@pytest.mark.parametrize("operation", [
    {"op": "set_controller_value", "label": "PC", "gain": 0.0},
    {"op": "set_controller_value", "label": "PC", "integral_s": 0.0},
    {"op": "set_controller_value", "label": "PC", "derivative_s": -1.0},
    {"op": "set_controller_value", "label": "PC", "setpoint": -5.0},
    {"op": "set_controller_value", "label": "PC"},
    {"op": "set_controller_value", "label": "PC", "bias": 0.2},
    {"op": "set_controller_value", "label": "NO_LOOP", "gain": 0.8},
])
def test_a_bad_loop_edit_is_refused(ws: Path, operation: dict) -> None:  # noqa: F811
    response = _plan(_rows(_loop_case(ws)), [operation])
    assert response.status_code in (200, 400, 422)
    if response.status_code == 200:
        assert response.json()["publishable"] is False


def test_coverage_names_the_loop_keys(ws: Path) -> None:  # noqa: F811
    case = _loop_case(ws)
    table = keyword_coverage(case, case_edit_table.editable_rows(case)["rows"])["table"]
    for key in ("PARAMETERS.SETPOINT", "PARAMETERS.AMPLIFICATION", "PARAMETERS.INTEGRALCONST", "PARAMETERS.DERIVATIVECONST"):
        assert key in table, key


def test_the_publish_card_shows_the_edited_setpoint(ws: Path) -> None:  # noqa: F811
    from olga_companion.agent import approval_display

    case = _loop_case(ws)
    plan = _plan(_rows(case), [{"op": "set_controller_value", "label": "PC", "setpoint": 2_500_000.0}]).json()
    args = {key: plan[key] for key in ("transaction_id", "source_hash", "compiled_hash", "context_generation")}
    card = approval_display.build("case_publish", args, locale="en")
    rows = {(row["group"], row["name"]): (row["value"], row["unit"]) for row in card["inputs"]}
    assert rows[("Control", "PC Setpoint")] == ("2500000", "Pa")
