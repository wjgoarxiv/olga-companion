"""Golden repro tests for the 2026-11-18 code review (docs/roadmap/code-review-2026-11-18.md)."""

from __future__ import annotations

import math
from copy import deepcopy

import pytest

from olga_companion import case_compiler, case_spec
from olga_companion.case_transactions import _render_end_time
from olga_companion.patrol_sanitization import safe_diagnostic_text
from olga_companion.result_series_view import apply_series_view
from olga_companion.run_companions import companion_references
from olga_companion.units import convert_values

from test_case_compiler import SPEC
from test_case_spec_validation import _supported_spec


def test_r1_empty_equipment_list_is_valid() -> None:
    raw = _supported_spec()
    raw["equipment"] = []
    result = case_spec.validate_case_spec(raw)
    assert result["valid"] is True, result["errors"]


@pytest.mark.parametrize(
    "text",
    [
        "Mass error 5.2 kg/s", "CFL 5 m/s", "GOR 100 Sm3/Sm3", "rate 10 m3/h", "rate 5 °/s", "(kg*m)/s",
        "U 5 W/m2-K", "gas 12 MMscf/d", "oil 300 SM3/D", "CGR 40 bbl/MMscf", "q 2 m³/s", "rate 3 t/h",
    ],
)
def test_r2_units_are_not_redacted(text: str) -> None:
    assert safe_diagnostic_text(text, 200) == text


@pytest.mark.parametrize(
    "text",
    [
        "open C:\\Users\\someone\\case.genkey failed",
        "open /home/someone/case.genkey failed",
        "FILE=/opt/x/y.tab",
        "open ../../Users/someone/case.genkey failed",
        "see Users/someone/x.out",
    ],
)
def test_r2_real_paths_are_still_redacted(text: str) -> None:
    safe = safe_diagnostic_text(text, 200)
    assert "someone" not in safe and "/opt/x" not in safe


def test_r3_one_nan_sample_does_not_break_the_series_view() -> None:
    view = apply_series_view(
        [0.0, 1.0, 2.0], [1.0, math.nan, 3.0], source_unit="bar", source_time_unit="s", value_unit="Pa"
    )
    assert view["values"] == [100000.0, 300000.0]
    assert view["time"] == [0.0, 2.0]
    assert view["view"]["dropped_non_finite"] == 1


def test_r3_same_unit_alias_is_identity() -> None:
    result = convert_values([15.1, 25.3], "°C", "C")
    assert result["values"] == [15.1, 25.3]


def test_r5_commented_pvtfile_is_ignored() -> None:
    text = '! FILES PVTFILE="old_fluid.tab"\nFILES PVTFILE="fluid.tab"\n'
    assert companion_references(text) == [("pvt", "fluid.tab")]


def test_r5_trailing_comma_is_not_part_of_the_name() -> None:
    assert companion_references("FILES PVTFILE=fluid.tab, X=1\n") == [("pvt", "fluid.tab")]


def test_r7_arithmetic_centerline_compiles() -> None:
    spec = deepcopy(SPEC)
    end = 30.480000000000004
    spec["flowpaths"][0]["pipes"][0]["centerline_m"] = [[0, 0, 0], [end, 0, 5]]
    spec["flowpaths"][1]["pipes"][0]["centerline_m"][0] = [end, 0, 5]
    spec["flowpaths"][2]["pipes"][0]["centerline_m"][0] = [end, 0, 5]
    case_compiler.compile_case_spec(spec)


@pytest.mark.parametrize("end", [3600.0000000000005, 0.1 * 3 * 3600 * 0.7])
def test_r7_arithmetic_end_time_compiles(end: float) -> None:
    spec = deepcopy(SPEC)
    spec["integration"]["end_time_s"] = end
    case_compiler.compile_case_spec(spec)


@pytest.mark.parametrize(
    "original, value, expected",
    [("3600.0", 7200.25, "7200.25"), ("3600", 1800.5, "1800.5"), ("1e5", 2e5, "200000"), ("3600", 7200.0, "7200")],
)
def test_r11_end_time_keeps_the_exact_value(original: str, value: float, expected: str) -> None:
    rendered = _render_end_time(original, value)
    assert rendered is not None and float(rendered) == value
    assert rendered == expected


def test_r5_commented_restart_readfile_is_ignored() -> None:
    assert companion_references("RESTART FILE=a.rsw ! READFILE=ON\n") == []


def test_r5_bang_inside_quotes_is_not_a_comment() -> None:
    text = 'FILES DIR="C:\\x!y", PVTFILE="a.tab"\n'
    assert companion_references(text) == [("pvt", "a.tab")]


def test_r5_bang_after_an_unquoted_name_ends_it() -> None:
    assert companion_references("FILES PVTFILE=fluid.tab!old\n") == [("pvt", "fluid.tab")]


def test_r3_an_empty_sample_is_dropped_like_nan() -> None:
    view = apply_series_view(
        [0.0, 1.0, 2.0], [1.0, None, 3.0], source_unit="bar", source_time_unit="s", value_unit="bar"
    )
    assert view["values"] == [1.0, 3.0]
    assert view["view"]["dropped_non_finite"] == 1


def test_r3_a_nan_outside_the_plotted_window_is_not_counted() -> None:
    view = apply_series_view(
        [0.0, 1.0, 2.0, 3.0], [math.nan, 1.0, 2.0, 3.0], source_unit="kg/s", source_time_unit="s",
        range_spec={"mode": "bounds", "start": 1, "end": 3},
    )
    assert view["view"]["dropped_non_finite"] == 0
