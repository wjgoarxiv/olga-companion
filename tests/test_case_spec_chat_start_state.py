"""A chat-built case can start from a stated state, and a circulation loop is built as two parallel flowpaths.

An airlift loop starts full of water: version 3 with steady state off and
initial conditions. Air enters the riser's first section; the bottom junction's
third leg is a short closed drain leg with a zero mass-flow source. The riser and the downcomer both run from the bottom
junction to the top junction, so the loop is not a directed cycle; the
downcomer then carries negative (downward) flow.
"""

from __future__ import annotations

import re

import pytest

from olga_companion.agent import runtime, tools
from olga_companion.case_compiler import render_case_spec
from case_spec_v2_support import with_v2_inputs


def _loop_spec() -> dict:
    spec = with_v2_inputs({
        "version": "3",
        "nodes": [
            {"label": "FEED", "kind": "closed"},
            {"label": "BOTTOM_J", "kind": "junction"},
            {"label": "TOP", "kind": "junction"},
            {
                "label": "VENT",
                "kind": "sink",
                "pressure_pa": 101_325,
                "temperature_c": 25,
                "gas_fraction": 1,
                "total_water_fraction": 0,
            },
        ],
        "flowpaths": [
            {
                "label": "DRAINLEG",
                "from": "FEED",
                "to": "BOTTOM_J",
                "pipes": [{"label": "SP", "centerline_m": [[0, -0.5, 0], [0, 0, 0]], "diameter_m": 0.1, "sections": 2}],
            },
            {
                "label": "RISER",
                "from": "BOTTOM_J",
                "to": "TOP",
                "pipes": [{"label": "R1", "centerline_m": [[0, 0, 0], [0, 10, 0]], "diameter_m": 0.1, "sections": 20}],
            },
            {
                "label": "DOWNCOMER",
                "from": "BOTTOM_J",
                "to": "TOP",
                "pipes": [
                    {"label": "D1", "centerline_m": [[0, 0, 0], [1, 0, 0]], "diameter_m": 0.1, "sections": 2},
                    {"label": "D2", "centerline_m": [[1, 0, 0], [1, 10, 0]], "diameter_m": 0.1, "sections": 20},
                    {"label": "D3", "centerline_m": [[1, 10, 0], [0, 10, 0]], "diameter_m": 0.1, "sections": 2},
                ],
            },
            {
                "label": "VENTLINE",
                "from": "TOP",
                "to": "VENT",
                "pipes": [{"label": "V1", "centerline_m": [[0, 10, 0], [0, 10.5, 0]], "diameter_m": 0.1, "sections": 2}],
            },
        ],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 60, "steady_state": False},
        "initial_conditions": {"pressure_pa": 101_325, "temperature_c": 25, "void_fraction": 0},
        "massflow_sources": [{
            "label": "AIR",
            "flowpath": "RISER",
            "pipe": "R1",
            "section": 1,
            "time_s": 0,
            "mass_flow_kg_s": 2.0e-4,
            "temperature_c": 25,
            "gas_fraction": 1,
            "total_water_fraction": 0,
        }, {
            "label": "DRAIN",
            "flowpath": "DRAINLEG",
            "pipe": "SP",
            "section": 1,
            "time_s": 0,
            "mass_flow_kg_s": 0,
            "temperature_c": 25,
            "gas_fraction": 0,
            "total_water_fraction": 1,
        }],
        "outputs": ["PT", "HOL", "GT"],
    })
    spec["version"] = "3"
    spec["flowpaths"][3]["initial_void_fraction"] = 1
    return spec


def test_the_chat_can_validate_a_water_filled_loop_with_a_stated_start_state() -> None:
    result = tools.dispatch("case_spec_validate", {"spec": _loop_spec()})

    assert result["valid"] is True, result.get("errors")


def test_the_loop_compiles_with_its_start_state_and_both_legs() -> None:
    text = render_case_spec(_loop_spec()).decode("utf-8")

    assert "STEADYSTATE=OFF" in text.replace(" ", "")
    assert "INITIALCONDITIONS" in text
    assert re.search(r'TAG=RISER\b', text)
    assert re.search(r'TAG=DOWNCOMER\b', text)


def test_a_directed_cycle_is_refused_with_the_parallel_way_to_build_a_loop() -> None:
    spec = _loop_spec()
    spec["flowpaths"][2]["from"], spec["flowpaths"][2]["to"] = "TOP", "BOTTOM_J"
    for pipe in spec["flowpaths"][2]["pipes"]:
        pipe["centerline_m"].reverse()
    spec["flowpaths"][2]["pipes"].reverse()

    result = tools.dispatch("case_spec_validate", {"spec": spec})

    assert result["valid"] is False
    message = " ".join(str(issue) for issue in result["errors"])
    assert "parallel" in message


@pytest.mark.parametrize(
    "phrase",
    [
        'version "3"',
        "initial_conditions",
        "initial_void_fraction",
        "two flowpaths from the bottom junction to the top junction",
    ],
)
def test_the_prompt_teaches_start_states_and_loops(phrase: str) -> None:
    assert phrase in " ".join(runtime.SYSTEM_PROMPT.split())
    assert "Do not write INITIALCONDITIONS." not in runtime.SYSTEM_PROMPT


def test_a_node_named_bottom_is_refused_because_olga_crashes_on_it() -> None:
    # OLGA 2022.1.0 stopped with an access violation and no log whenever a junction
    # was labelled BOTTOM; the same case with the junction renamed ran to a normal stop.
    spec = _loop_spec()
    spec["nodes"][1]["label"] = "BOTTOM"
    for flowpath in spec["flowpaths"]:
        for end in ("from", "to"):
            if flowpath[end] == "BOTTOM_J":
                flowpath[end] = "BOTTOM"

    result = tools.dispatch("case_spec_validate", {"spec": spec})

    assert result["valid"] is False
    issue = next(issue for issue in result["errors"] if issue["code"] == "reserved_label")
    assert "BOTTOM" in issue["guidance"]


def test_a_flowpath_with_one_section_is_refused_because_olga_stops_on_it() -> None:
    # OLGA 2022.1.0 aborted at time 0: "The total number of segments is less than 2".
    spec = _loop_spec()
    spec["flowpaths"][3]["pipes"][0]["sections"] = 1

    result = tools.dispatch("case_spec_validate", {"spec": spec})

    assert result["valid"] is False
    issue = next(issue for issue in result["errors"] if issue["code"] == "flowpath_needs_two_sections")
    assert "2" in issue["guidance"]
