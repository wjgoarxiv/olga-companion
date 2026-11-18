"""N4: one strict reader for typed numbers; ambiguous text is refused, never guessed."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from olga_companion import pipe_table, pipe_table_import
from olga_companion.strict_number import parse_number

CASES = json.loads((Path(__file__).parent / "fixtures" / "strict_number_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("text", "expected"), CASES["accepted"])
def test_plain_numbers_are_read(text: str, expected: float) -> None:
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", CASES["refused"])
def test_ambiguous_or_odd_text_is_refused(text: str) -> None:
    assert parse_number(text) is None


@pytest.mark.parametrize("text", CASES["comma_off_refused"])
def test_a_comma_is_refused_where_it_separates_values(text: str) -> None:
    assert parse_number(text, decimal_comma=False) is None


def test_non_text_values() -> None:
    assert parse_number(3) == 3.0
    assert parse_number(2.5) == 2.5
    assert parse_number(True) is None
    assert parse_number(float("nan")) is None
    assert parse_number(None) is None


def test_property_every_finite_float_round_trips_through_its_text() -> None:
    rng = random.Random(20261118)
    for _ in range(5000):
        number = rng.uniform(-1e6, 1e6) * 10 ** rng.randint(-12, 12)
        for text in (repr(number), f"{number:.6g}", f"{number:e}", f"  {number}  "):
            assert parse_number(text) == pytest.approx(float(text), rel=0, abs=0), text


def test_property_a_decimal_comma_reads_as_the_point_unless_it_looks_like_thousands() -> None:
    rng = random.Random(7)
    for _ in range(5000):
        whole, frac = rng.randint(0, 99999), rng.randint(0, 9999)
        text = f"{whole},{frac:0{rng.randint(1, 4)}d}"
        head, tail = text.split(",")
        looks_grouped = len(head) <= 3 and len(tail) == 3
        result = parse_number(text)
        if looks_grouped:
            assert result is None, text
        else:
            assert result == float(f"{head}.{tail}"), text


def test_property_junk_around_a_number_is_always_refused() -> None:
    rng = random.Random(11)
    junk = ["_", "x", "#", "$", "%", "a", ",", ".", "e"]
    for _ in range(3000):
        base = f"{rng.uniform(-1e3, 1e3):.3f}"
        text = base + rng.choice(junk) if rng.random() < 0.5 else rng.choice(junk[:6]) + base
        result = parse_number(text)
        assert result is None or math.isfinite(result)
        assert result is None, text


def test_the_pipe_table_reader_uses_it() -> None:
    assert pipe_table._number("0,05") == 0.05
    assert pipe_table._number("1,500") is None
    assert pipe_table._number("1_000") is None
    assert pipe_table._number("nan") is None
    assert pipe_table._number("inf") is None
    assert pipe_table._number(12) == 12.0


def test_a_valve_opening_refuses_odd_text_and_a_comma_stays_a_separator() -> None:
    for text in ("nan", "inf", "1_0"):
        points, problem, _code = pipe_table_import._schedule(text)
        assert points is None and problem, text
    points, problem, _ = pipe_table_import._schedule("0.5")
    assert points == [(0.0, 0.5)] and problem is None
    # "0,5" is two schedule entries without time:opening pairs, never a decimal 0.5.
    points, problem, code = pipe_table_import._schedule("0,5")
    assert points is None and problem and code == "valve_schedule_bad_format"
    assert pipe_table_import._schedule("0:1, 300:0")[0] == [(0.0, 1.0), (300.0, 0.0)]
