"""0.1.21 row 3: the agent can propose a PID loop through the strict schema, and the card shows it."""

from __future__ import annotations

import pytest
from test_casespec_controller import _spec

from olga_companion import case_spec
from olga_companion.agent import approval_display
from olga_companion.agent.json_schema_validation import SchemaValidationError, validate_json_schema


def _loop_rows(locale: str) -> list[tuple[str, str, str]]:
    spec = case_spec.normalize_case_spec(_spec())
    group = "제어" if locale == "ko" else "Control"
    return [
        (row["name"], row["value"], row["unit"])
        for row in approval_display.reviewed_inputs(spec, locale=locale)
        if row["group"] == group
    ]


def test_the_card_shows_every_loop_value_in_english() -> None:
    rows = _loop_rows("en")
    assert ("PC_A Measures", "Pressure (PT) at PIPE_A section 3", "") in rows
    assert ("PC_A Valve", "VALVE_A", "") in rows
    assert ("PC_A Setpoint", "1500000", "Pa") in rows
    assert ("PC_A Gain", "-0.5", "") in rows
    assert ("PC_A Direction", "Opens the valve when the reading is below the setpoint", "") in rows
    assert ("PC_A Integral time", "60", "s") in rows
    assert ("PC_A Derivative time", "0", "s") in rows
    assert ("PC_A Bias", "1", "-") in rows
    assert ("PC_A Normalising range", "100000", "Pa") in rows
    assert ("PC_A Stroke time", "10", "s") in rows


def test_the_card_shows_the_loop_in_korean_with_flow_units() -> None:
    measure = {"variable": "GT", "flowpath": "MAIN", "pipe": "PIPE_A", "section": 8}
    spec = case_spec.normalize_case_spec(_spec(measure=measure, setpoint=2.5, norm_range=1.0, gain=0.4))
    rows = [
        (row["name"], row["value"], row["unit"])
        for row in approval_display.reviewed_inputs(spec, locale="ko")
        if row["group"] == "제어"
    ]
    assert ("PC_A 측정", "질량유량 (GT) PIPE_A 구간 8", "") in rows
    assert ("PC_A 설정값", "2.5", "kg/s") in rows
    assert ("PC_A 동작 방향", "측정값이 설정값보다 크면 밸브를 엽니다", "") in rows
    assert ("PC_A 적분 시간", "60", "s") in rows


def test_the_agent_schema_accepts_a_loop() -> None:
    validate_json_schema(case_spec.case_spec_inline_schema(), _spec())


@pytest.mark.parametrize("forged", ["approved", "mode", "approval_token"])
def test_the_agent_schema_refuses_extra_loop_fields(forged: str) -> None:
    raw = _spec()
    raw["controllers"][0][forged] = True
    with pytest.raises(SchemaValidationError, match=forged):
        validate_json_schema(case_spec.case_spec_inline_schema(), raw)


def test_the_new_case_checklist_offers_an_optional_pid_loop() -> None:
    from olga_companion.case_intake import api_case_spec_requirements

    items = {
        item["key"]: item
        for group in api_case_spec_requirements()["groups"]
        for item in group["items"]
    }
    assert items["equipment.controller"]["required"] is False


def test_the_agent_is_told_how_a_loop_is_built_and_which_way_the_gain_acts() -> None:
    loops = case_spec.case_spec_capabilities()["controllers"]
    assert loops["version"] == "3"
    assert loops["measure_variables"] == {"PT": "Pa", "GT": "kg/s"}
    assert "above the setpoint" in loops["gain_sign"]
    assert "setpoint" in " ".join(loops["user_must_state"])


def test_a_controller_sent_as_equipment_is_pointed_at_the_controllers_field() -> None:
    from case_spec_v2_support import with_v2_inputs
    from test_case_spec_validation import _supported_spec

    raw = _supported_spec()
    raw["equipment"] = [{"kind": "controller", "label": "CTRL_A"}]
    issue = case_spec.validate_case_spec(with_v2_inputs(raw))["errors"][0]
    assert issue["code"] == "unsupported_equipment"
    assert "controllers" in issue["guidance"]


def test_the_edit_plan_tool_refuses_a_forged_loop_field() -> None:
    from olga_companion.agent import tools

    raw = _spec()
    raw["controllers"][0]["approved"] = True
    args = {"spec": raw, "spec_hash": "0" * 64, "destination_rel": "cases/loop.genkey", "operations": []}
    with pytest.raises(SchemaValidationError, match="approved"):
        validate_json_schema(tools.TOOLS["case_edit_plan"].parameters, args)
