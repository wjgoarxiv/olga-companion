from __future__ import annotations

import math

import pytest


@pytest.mark.parametrize(
    "source, target, value, expected",
    [
        ("Pa", "bar", 100_000.0, 1.0),
        ("kPa", "psi", 100.0, 14.503773773),
        ("s", "h", 3600.0, 1.0),
        ("kg/s", "t/h", 1.0, 3.6),
        ("lb/h", "kg/h", 1.0, 0.45359237),
        ("m3/s", "L/s", 1.0, 1000.0),
        ("m", "ft", 1.0, 3.280839895),
        ("ft/s", "m/s", 1.0, 0.3048),
        ("fraction", "%", 0.25, 25.0),
    ],
)
def test_unit_registry_converts_only_allowlisted_compatible_units(
    source: str, target: str, value: float, expected: float
) -> None:
    from olga_companion.units import convert_values

    source_values = [value]
    result = convert_values(source_values, source, target)

    assert result["values"] == pytest.approx([expected])
    assert result["unit"] == target
    assert result["conversion"]["status"] == "converted"
    assert result["conversion"]["source_unit"] == source
    assert result["conversion"]["requested_unit"] == target
    assert source_values == [value], "conversion must not mutate parser-owned arrays"


def test_temperature_point_and_delta_conversions_are_explicitly_distinct() -> None:
    from olga_companion.units import convert_values

    point = convert_values([10.0], "C", "F", quantity_kind="point")
    delta = convert_values([10.0], "C", "F", quantity_kind="delta")

    assert point["values"] == pytest.approx([50.0])
    assert delta["values"] == pytest.approx([18.0])
    assert point["conversion"]["quantity_kind"] == "point"
    assert delta["conversion"]["quantity_kind"] == "delta"


@pytest.mark.parametrize("requested", ["pa", "Pa"])
def test_known_source_alias_emits_registry_canonical_spelling(requested: str) -> None:
    from olga_companion.units import convert_values

    result = convert_values([100_000.0], "PA", requested)

    assert result["values"] == [100_000.0]
    assert result["unit"] == "Pa"
    assert result["conversion"]["status"] == "converted"
    assert result["conversion"]["output_unit"] == "Pa"


@pytest.mark.parametrize("source", ["barg", "psig", "bara", "psia"])
def test_explicit_pressure_reference_units_remain_source_only(source: str) -> None:
    from olga_companion.units import convert_values

    result = convert_values([1.0], source, "bar")

    assert result["values"] == [1.0]
    assert result["unit"] == source
    assert result["conversion"]["status"] == "source_only"
    assert result["conversion"]["reason"] == "explicit_pressure_reference_requires_metadata"


def test_unknown_and_incompatible_units_return_honest_source_only_metadata() -> None:
    from olga_companion.units import convert_values

    unknown = convert_values([4.0], "sm3/d", "m3/h")
    unknown_identity = convert_values([4.0], "sm3/d", "sm3/d")
    incompatible = convert_values([4.0], "m", "s")

    assert unknown["conversion"]["status"] == "source_only"
    assert unknown["conversion"]["reason"] == "unknown_source_unit"
    assert unknown["unit"] == "sm3/d"
    assert unknown_identity["conversion"]["status"] == "source_only"
    assert unknown_identity["conversion"]["reason"] == "unknown_source_unit"
    assert incompatible["conversion"]["status"] == "source_only"
    assert incompatible["conversion"]["reason"] == "incompatible_dimensions"


@pytest.mark.parametrize("unit", ["", " Pa", "Pa\n", "x" * 65])
def test_malformed_requested_units_are_rejected(unit: str) -> None:
    from olga_companion.units import convert_values

    with pytest.raises(ValueError, match="unit"):
        convert_values([1.0], "Pa", unit)


def test_non_finite_values_are_rejected() -> None:
    from olga_companion.units import convert_values

    with pytest.raises(ValueError, match="finite"):
        convert_values([math.inf], "Pa", "bar")
