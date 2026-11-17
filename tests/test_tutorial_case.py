"""Tutorial demo case: synthetic air-water horizontal pipe validates clean."""

from __future__ import annotations

import json
from pathlib import Path

from olga_companion import case_spec, starter_fluids

TUTORIAL_DIR = Path(__file__).resolve().parent.parent / "resources" / "tutorial"
DEMO_CASE = TUTORIAL_DIR / "demo_case.json"


def _load_demo() -> dict:
    return json.loads(DEMO_CASE.read_text(encoding="utf-8"))


def test_demo_case_validates_and_is_publishable() -> None:
    raw = _load_demo()
    result = case_spec.validate_case_spec(raw)
    assert result["valid"] is True, result["errors"]
    assert result["publishable"] is True
    assert result["errors"] == []


def test_demo_case_links_the_bundled_starter_table() -> None:
    raw = _load_demo()
    assert raw["fluid_label"] == starter_fluids.LABEL
    assert str(raw["pvt_reference"]).endswith(".tab")
    assert " " not in str(raw["pvt_reference"])


def test_demo_case_stays_inside_the_starter_table_range() -> None:
    raw = _load_demo()
    lo_pa, hi_pa = starter_fluids.PRESSURE_RANGE_BAR[0] * 1e5, starter_fluids.PRESSURE_RANGE_BAR[1] * 1e5
    lo_c, hi_c = starter_fluids.TEMPERATURE_RANGE_C
    for node in raw["nodes"]:
        if "pressure_pa" in node:
            assert lo_pa <= node["pressure_pa"] <= hi_pa
        if "temperature_c" in node:
            assert lo_c <= node["temperature_c"] <= hi_c


def test_demo_case_is_a_horizontal_pipe_with_synthetic_labels() -> None:
    raw = _load_demo()
    assert len(raw["flowpaths"]) == 1
    pipe = raw["flowpaths"][0]["pipes"][0]
    heights = {point[2] for point in pipe["centerline_m"]}
    assert len(heights) == 1
    text = DEMO_CASE.read_text(encoding="utf-8")
    assert "@" not in text
    assert "C:\\" not in text and "C:/" not in text
