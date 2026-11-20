"""Output cadence follows the end time, and case-level trends stay grounded."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from olga_companion import case_compiler, case_spec
from olga_companion.agent.runtime import SYSTEM_PROMPT
from olga_companion.case_intake import api_case_spec_requirements

FIXTURE = Path(__file__).parent / "fixtures" / "casespec_outputs.json"


def _spec() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_case_level_trend_keeps_only_the_grounded_global_variable() -> None:
    compiled = case_compiler.compile_case_spec(_spec())
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert [line for line in text.splitlines() if line.startswith("TRENDDATA VARIABLE=")] == [
        "TRENDDATA VARIABLE=LIQC"
    ]
    assert (
        "TRENDDATA POSITION=(POS_MAIN_1, POS_MAIN), "
        "VARIABLE=(GT, HOL, ID, PT, QLT, TM)"
    ) in text


def test_absent_intervals_follow_the_end_time_and_omit_max_dt() -> None:
    raw = _spec()
    raw["integration"] = {"end_time_s": 60.0}

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert "OUTPUT DTOUT=60 s" in text
    assert "TREND DTPLOT=1 s" in text
    assert "PROFILE DTPLOT=15 s" in text
    assert "MAXDT=" not in text


def test_stated_intervals_and_a_bounded_max_dt_are_emitted() -> None:
    raw = _spec()
    raw["integration"] = {
        "end_time_s": 60.0,
        "trend_interval_s": 2.0,
        "profile_interval_s": 10.0,
        "output_interval_s": 30.0,
        "max_dt_s": 6.0,
    }

    compiled = case_compiler.compile_case_spec(raw)
    text = compiled.text

    assert compiled.validation.clean is True, compiled.validation.diagnostics
    assert "OUTPUT DTOUT=30 s" in text
    assert "TREND DTPLOT=2 s" in text
    assert "PROFILE DTPLOT=10 s" in text
    assert "MAXDT=6 s" in text


def test_interval_below_mindt_is_an_issue_code() -> None:
    raw = _spec()
    raw["integration"] = {"end_time_s": 60.0, "trend_interval_s": 0.0001}

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "interval_below_min_dt"
    with pytest.raises(ValidationError):
        case_compiler.render_case_spec(raw)


def test_absurd_interval_count_is_an_issue_code() -> None:
    raw = _spec()
    raw["integration"] = {"end_time_s": 3600.0, "output_interval_s": 0.01}

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "interval_count_exceeds_limit"


def test_max_dt_larger_than_one_tenth_of_end_time_is_refused() -> None:
    raw = _spec()
    raw["integration"] = {"end_time_s": 60.0, "max_dt_s": 7.0}

    result = case_spec.validate_case_spec(raw)

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "max_dt_exceeds_end_fraction"
    with pytest.raises(ValidationError):
        case_compiler.render_case_spec(raw)


def test_intake_and_prompt_ask_for_the_output_cadence() -> None:
    by_key = {
        item["key"]: item
        for group in api_case_spec_requirements()["groups"]
        for item in group["items"]
    }

    for key in (
        "time.trend_interval_s",
        "time.profile_interval_s",
        "time.output_interval_s",
        "time.max_dt_s",
    ):
        assert by_key[key]["required"] is False
        assert by_key[key]["unit"] == "s"
    assert "trend_interval_s" in SYSTEM_PROMPT
    assert "end time divided by 60" in SYSTEM_PROMPT
