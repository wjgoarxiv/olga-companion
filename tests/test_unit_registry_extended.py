"""Owner request 2026-11-16: graph units should convert freely.

The registry gained common field units (atm, kgf/cm2, day, bbl/d, ...) and two
dimensions OLGA writes often (density, volume). Every unit the graph offers
must be one the backend converts, in the same dimension.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from olga_companion.units import UNIT_REGISTRY, convert_values

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (101_325.0, "Pa", "atm", 1.0),
        (98_066.5, "Pa", "kgf/cm2", 1.0),
        (1.0, "atm", "bar", 1.01325),
        (86_400.0, "s", "d", 1.0),
        (1.0, "t/d", "kg/s", 1_000.0 / 86_400.0),
        (1.0, "L/min", "m3/h", 0.06),
        (1.0, "m3/s", "bbl/d", 86_400.0 / 0.158987294928),
        (0.0254, "m", "in", 1.0),
        (3.6, "km/h", "m/s", 1.0),
        (1_000.0, "kg/m3", "g/cm3", 1.0),
        (16.01846337396, "kg/m3", "lb/ft3", 1.0),
        (1.0, "m3", "L", 1_000.0),
        (0.158987294928, "m3", "bbl", 1.0),
        (0.028316846592, "m3", "ft3", 1.0),
    ],
)
def test_new_units_convert(value, source, target, expected):
    result = convert_values([value], source, target)
    assert result["conversion"]["status"] == "converted"
    assert result["values"][0] == pytest.approx(expected, rel=1e-9)


def test_density_and_volume_do_not_mix():
    result = convert_values([1.0], "kg/m3", "m3")
    assert result["conversion"]["status"] == "source_only"
    assert result["conversion"]["reason"] == "incompatible_dimensions"


def test_every_graph_unit_choice_is_a_backend_unit_of_the_same_dimension():
    source = (ROOT / "frontend" / "src" / "unitPreferences.mjs").read_text(encoding="utf-8")
    block = source[source.index("UNIT_CHOICES"):source.index("}));")]
    rows = re.findall(r"(\w+): Object\.freeze\(\[([^\]]*)\]\)", block)
    assert rows, "no unit choices found"
    for dimension, units in rows:
        for unit in re.findall(r"'([^']+)'", units):
            assert unit in UNIT_REGISTRY, f"{unit} is offered but not convertible"
            assert UNIT_REGISTRY[unit].dimension == dimension, f"{unit} is not {dimension}"


@pytest.mark.parametrize(("source", "expected_k"), [("°C", 273.15), ("degC", 273.15), ("°F", 255.3722222222222)])
def test_degree_sign_temperatures_convert(source, expected_k):
    # OLGA writes TM in "°C"; without the alias every temperature graph was locked.
    result = convert_values([0.0], source, "K")
    assert result["conversion"]["status"] == "converted"
    assert result["values"][0] == pytest.approx(expected_k)
    assert convert_values([0.0], source, None)["conversion"]["dimension"] == "temperature"
