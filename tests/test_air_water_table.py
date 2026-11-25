"""The bundled air-water table: where it comes from, and that its numbers are physically right.

The reference values are published ones (IAPWS for water, the Lemmon air equation and the
ASHRAE saturation data for moist air), typed here so the test needs no property library.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from olga_companion import fluid_table, starter_fluids

REPO = Path(__file__).resolve().parents[1]
TABLE = REPO / "resources" / "fluids" / starter_fluids.TABLE_NAME
P_BAR = [0.5, 0.8, 1.01325, 1.2, 1.5, 2, 3, 5, 8, 12, 16, 20]
OIL_OFFSET = 250.0  # the placeholder oil sits this far below dry air, J/kg
T_C = [0, 10, 20, 25, 30, 40, 50, 60, 70, 80]


@pytest.fixture(scope="module")
def grid() -> dict[tuple[float, float], dict[str, float]]:
    text = TABLE.read_text(encoding="ascii")
    columns = [c.strip() for c in re.search(r"COLUMNS\s*=\s*\(([^)]*)\)", text).group(1).split(",")]
    rows = {}
    for match in re.finditer(r"^PVTTABLE POINT = \(([^)]*)\)", text, re.M):
        values = [float(v) for v in match.group(1).split(",")]
        assert len(values) == len(columns) and all(math.isfinite(v) for v in values)
        row = dict(zip(columns, values, strict=True))
        rows[(round(row["PT"] / 1e5, 6), round(row["TM"], 6))] = row
    return rows


def test_the_only_bundled_fluid_is_computed_from_open_equations() -> None:
    assert [p.name for p in TABLE.parent.iterdir()] == ["air_water.tab"]
    text = TABLE.read_text(encoding="ascii")
    assert "scripts/build_air_water_tab.py" in text and "CoolProp" in text
    for mark in ("Multiflash", "Infochem", "CPA", "PVTsim", "HYSYS"):
        assert mark not in text
    check = fluid_table.pickup_tab(str(TABLE), starter_fluids.LABEL)
    assert check["valid"] is True, check["errors"]
    # The steps are where the mixture's water has all become vapour; the constant is the absent oil's.
    assert {w["location"].split()[0] for w in check["warnings"]} == {"RSW", "SIGGHL"}


def test_the_grid_is_the_one_the_examples_were_made_for(grid) -> None:
    assert set(grid) == {(p, t) for p in P_BAR for t in T_C}
    assert starter_fluids.TEMPERATURE_RANGE_C == (min(T_C), max(T_C))
    assert starter_fluids.PRESSURE_RANGE_BAR == (min(P_BAR), max(P_BAR))


@pytest.mark.parametrize(
    ("p", "t", "column", "expected", "rel"),
    [
        (1.01325, 25, "ROWT", 997.047, 1e-5),  # IAPWS-95
        (1.01325, 80, "ROWT", 971.79, 5e-5),
        (20, 25, "ROWT", 997.90, 5e-5),
        (1.01325, 25, "VISWT", 8.900e-4, 2e-3),  # IAPWS 2008
        (1.01325, 25, "CPWT", 4181.3, 1e-3),
        (1.01325, 25, "TCWT", 0.6065, 3e-3),  # IAPWS 2011
        (1.01325, 25, "SIGGWT", 0.07197, 2e-3),  # IAPWS 2014
        (1.01325, 80, "SIGGWT", 0.06267, 2e-3),
        (1.01325, 0, "ROHL", 1.2929, 1e-3),  # dry air
        (1.01325, 20, "ROHL", 1.2045, 1e-3),
        (1.01325, 25, "CPHL", 1006.3, 1e-3),
        (1.01325, 25, "VISHL", 1.845e-5, 5e-3),
        (1.01325, 25, "ROG", 1.1698, 2e-3),  # saturated moist air
        (1.01325, 25, "RSW", 0.0198, 1e-2),  # saturation humidity, kg per kg moist air
    ],
)
def test_a_value_matches_the_published_one(grid, p, t, column, expected, rel) -> None:
    assert grid[(p, t)][column] == pytest.approx(expected, rel=rel)


def test_the_latent_heat_is_waters(grid) -> None:
    """Both phases use one datum: vapour leaving the water carries the latent heat."""
    for t, latent in ((25, 2441.7e3), (80, 2308.0e3)):
        row = grid[(1.01325, t)]
        dry = row["HHL"] + OIL_OFFSET
        vapour = (row["HG"] - (1 - row["RSW"]) * dry) / row["RSW"]
        assert vapour - row["HWT"] == pytest.approx(latent, rel=2e-3)


def test_the_columns_agree_with_each_other(grid) -> None:
    for p in P_BAR:
        for low, high in zip(T_C, T_C[1:]):
            a, b = grid[(p, low)], grid[(p, high)]
            step = high - low
            for phase in ("HL", "WT"):
                cp = (a["CP" + phase] + b["CP" + phase]) / 2
                assert (b["H" + phase] - a["H" + phase]) / step == pytest.approx(cp, rel=1.5e-3)
                kelvin = (low + high) / 2 + 273.15
                assert (b["SE" + phase] - a["SE" + phase]) / step == pytest.approx(cp / kelvin, rel=3e-3)
            slope = (b["ROHL"] - a["ROHL"]) / step
            assert slope == pytest.approx((a["DROHLDT"] + b["DROHLDT"]) / 2, rel=5e-3)
    for t in T_C:
        for low, high in zip(P_BAR, P_BAR[1:]):
            a, b = grid[(low, t)], grid[(high, t)]
            for phase, rel in (("HL", 1e-3), ("WT", 3e-2)):
                slope = (b["RO" + phase] - a["RO" + phase]) / ((high - low) * 1e5)
                assert slope == pytest.approx((a[f"DRO{phase}DP"] + b[f"DRO{phase}DP"]) / 2, rel=rel)


def test_every_transport_and_density_is_positive_and_gas_is_lighter_than_dry_air(grid) -> None:
    for row in grid.values():
        for column in ("ROG", "ROHL", "ROWT", "VISG", "VISHL", "VISWT", "CPG", "CPHL", "CPWT", "TCG", "TCHL", "TCWT",
                       "SIGGHL", "SIGGWT", "SIGHLWT", "DROGDP", "DROHLDP", "DROWTDP"):
            assert row[column] > 0, column
        assert row["ROG"] < row["ROHL"] and row["RS"] == 1.0 and 0 < row["RSW"] < 1
        assert row["DROGDT"] < 0 and row["DROHLDT"] < 0


def test_the_gas_never_holds_more_water_than_the_mixture_has(grid) -> None:
    total = float(re.search(r"TOTWATERFRACTION = \(([^)]*)\)", TABLE.read_text(encoding="ascii")).group(1))
    full = {key for key, row in grid.items() if row["RSW"] == pytest.approx(total, rel=1e-6)}
    assert full == {(0.5, 70), (0.5, 80), (0.8, 80)}
    assert all(row["RSW"] <= total * (1 + 1e-6) for row in grid.values())


def test_the_gas_derivatives_are_at_fixed_composition(grid) -> None:
    """A nearly ideal gas of fixed composition: d(rho)/dP = rho/P and d(rho)/dT = -rho/T."""
    for (p, t), row in grid.items():
        if p <= 2:
            assert row["DROGDP"] * p * 1e5 / row["ROG"] == pytest.approx(1, rel=1e-2)
            assert -row["DROGDT"] * (t + 273.15) / row["ROG"] == pytest.approx(1, rel=3e-2)


def test_olga_has_no_enthalpy_to_complain_about(grid) -> None:
    """OLGA flags every node whose gas enthalpy is below the oil one; the oil columns are only placeholders."""
    assert [key for key, row in grid.items() if row["HG"] <= row["HHL"]] == []


def test_the_envelope_is_that_of_air() -> None:
    text = TABLE.read_text(encoding="ascii")

    def numbers(key: str) -> list[float]:
        return [float(v) for v in re.search(rf"\b{key}\s*=\s*\(([^)]*)\)", text).group(1).split(",")]

    assert numbers("CRITICALPRESSURE")[0] == pytest.approx(3.786e6, rel=1e-3)
    assert numbers("CRITICALTEMPERATURE")[0] == pytest.approx(-140.62, abs=0.02)
    for kind in ("BUBBLE", "DEW"):
        pressures, temperatures = numbers(kind + "PRESSURES"), numbers(kind + "TEMPERATURES")
        assert len(pressures) == len(temperatures) >= 20
        assert pressures == sorted(pressures) and temperatures == sorted(temperatures)
