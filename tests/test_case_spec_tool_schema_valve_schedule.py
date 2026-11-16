"""The model-facing case_spec tool schema carries the v3 valve schedule.

Hyper-real round 6 (2026-11-11, build H, xai grok-4.7): the model said three times that it
would put the valve schedule (0 s: 1, 60 s: 1, 70 s: 0) into the spec, and every
case_spec_validate/compile call arrived without it. The closed tool schema lists a valve
as kind/label/flowpath/pipe/position/diameter_m/opening with additionalProperties false,
so `schedule` could not be sent; CaseSpec v3 itself accepts it.
"""
from __future__ import annotations

import pytest

from olga_companion.agent import tools
from olga_companion.agent.tool_validation import ToolError, validate_tool_arguments

SCHEDULED_VALVE = {
    "kind": "valve",
    "label": "VALVE_1",
    "flowpath": "MAIN",
    "pipe": "PIPE_1",
    "position": 1,
    "diameter_m": 0.15,
    "opening": 1,
    "schedule": [
        {"time_s": 0, "opening": 1},
        {"time_s": 60, "opening": 1},
        {"time_s": 70, "opening": 0},
    ],
}


def _spec(valve: dict) -> dict:
    return {
        "version": "3",
        "nodes": [
            {"label": "INLET", "kind": "closed"},
            {"label": "OUTLET", "kind": "sink", "pressure_pa": 500000, "temperature_c": 20,
             "gas_fraction": 1, "total_water_fraction": 0.990099},
        ],
        "flowpaths": [{"label": "MAIN", "from": "INLET", "to": "OUTLET", "pipes": [
            {"label": "PIPE_1", "centerline_m": [[0, 0, 0], [500, 0, 0]], "diameter_m": 0.15,
             "roughness_m": 2e-6, "sections": 50},
        ]}],
        "pvt_reference": "air_water.tab",
        "fluid_label": "AIR_WATER",
        "thermal": {"model": "adiabatic"},
        "integration": {"end_time_s": 180},
        "outputs": ["PT"],
        "equipment": [valve],
    }


@pytest.mark.parametrize("name", ["case_spec_validate", "case_spec_compile"])
def test_a_scheduled_valve_passes_the_tool_schema(name: str) -> None:
    validate_tool_arguments(name, {"spec": _spec(SCHEDULED_VALVE)}, tools.TOOLS[name].parameters)


def test_a_schedule_point_with_an_unknown_field_is_still_refused() -> None:
    valve = {**SCHEDULED_VALVE, "schedule": [{"time_s": 0, "opening": 1, "speed": 2}, {"time_s": 5, "opening": 0}]}
    with pytest.raises(ToolError):
        validate_tool_arguments(
            "case_spec_validate", {"spec": _spec(valve)}, tools.TOOLS["case_spec_validate"].parameters
        )
