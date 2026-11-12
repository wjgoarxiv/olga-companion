"""OLGA's vertical axis is Y: every text the chat model sees says so.

A centerline point is [x, y, z] compiled straight to XEND/YEND/ZEND, and OLGA reads
YEND as elevation. A 10 m riser written on z ran flat, so the schema, the prompt and
the capability matrix must all say that height is y.
"""

from __future__ import annotations

import re

import pytest

from olga_companion.agent import runtime, tools
from olga_companion.case_compiler import render_case_spec
from case_spec_v2_support import with_v2_inputs


def _riser_spec() -> dict:
    return with_v2_inputs({
        "version": "2",
        "nodes": [
            {"label": "IN", "kind": "source", "pressure_pa": 200_000},
            {"label": "OUT", "kind": "sink", "pressure_pa": 100_000},
        ],
        "flowpaths": [{
            "label": "FP",
            "from": "IN",
            "to": "OUT",
            "pipes": [{"label": "R1", "centerline_m": [[0, 0, 0], [0, 10, 0]], "diameter_m": 0.1, "sections": 10}],
        }],
        "pvt_reference": "fluid.tab",
        "integration": {"end_time_s": 60},
        "outputs": ["PT"],
    })


def _words(text: str) -> str:
    return " ".join(text.split())


def test_a_riser_written_on_y_compiles_to_yend_and_a_flat_z() -> None:
    text = render_case_spec(_riser_spec()).decode("utf-8")

    assert re.search(r"YEND=10 m", text), text
    assert re.search(r"ZEND=0 m", text), text


@pytest.mark.parametrize("name", ["case_spec_validate", "case_spec_compile"])
def test_the_schema_sent_to_the_model_calls_y_the_elevation(name: str) -> None:
    spec = next(item for item in tools.tool_specs() if item["name"] == name)
    pipe = spec["parameters"]["properties"]["spec"]["properties"]["flowpaths"]["items"]["properties"][
        "pipes"
    ]["items"]["properties"]
    centerline = pipe["centerline_m"]
    point = centerline["items"]

    for description in (_words(centerline["description"]), _words(point["description"])):
        assert "y is elevation" in description or "y changes" in description or "changes y only" in description
        assert "OLGA vertical axis" in description or "[[0,0,0],[0,10,0]]" in description.replace(" ", "")
    assert "y is elevation (OLGA vertical axis)" in _words(point["description"])
    assert "[[0,0,0],[0,10,0]]" in _words(centerline["description"]).replace(" ", "")


def test_the_validate_description_says_olga_is_y_up() -> None:
    assert "Y-up" in tools.TOOLS["case_spec_validate"].description


def test_the_pipe_table_import_vertical_axis_clause_says_olga_is_y_up() -> None:
    description = tools.TOOLS["pipe_table_import"].description
    assert "table height column; OLGA is Y-up" in _words(description)


def test_the_system_prompt_states_y_is_the_vertical_axis() -> None:
    prompt = _words(runtime.SYSTEM_PROMPT)

    assert "In a centerline_m point [x, y, z], y is the vertical axis" in prompt
    assert "put a riser's rise on y, never on z" in prompt


def test_the_capabilities_carry_a_coordinate_axes_entry_next_to_units() -> None:
    result = tools.dispatch("case_spec_validate", {"spec": _riser_spec()})
    capabilities = result["capabilities"]

    axes = capabilities["coordinate_axes"]
    assert axes["vertical"] == "y"
    assert axes["horizontal"] == ["x", "z"]
    assert capabilities["units"]["coordinate"] == "m"
    assert set(capabilities["units"]) == {
        "coordinate", "diameter", "roughness", "pressure", "temperature", "time",
    }


def test_the_geometry_guidance_repeats_that_y_is_elevation() -> None:
    spec = _riser_spec()
    spec["flowpaths"][0]["pipes"][0]["centerline_m"] = [[0, 0, 0], [0, 0, 0]]

    result = tools.dispatch("case_spec_validate", {"spec": spec})

    issue = next(item for item in result["errors"] if item["code"] == "invalid_geometry")
    assert "y is elevation" in issue["guidance"]


def test_the_topology_guidance_repeats_that_y_is_elevation() -> None:
    spec = _riser_spec()
    spec["flowpaths"][0]["from"], spec["flowpaths"][0]["to"] = "OUT", "IN"

    result = tools.dispatch("case_spec_validate", {"spec": spec})

    issue = next(item for item in result["errors"] if item["code"] == "invalid_topology")
    assert "y is elevation" in issue["guidance"]
