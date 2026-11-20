"""0.1.20 row 1: the approval card names the heat-transfer model and every thermal value."""
from __future__ import annotations

import json
from pathlib import Path

from olga_companion import case_spec
from olga_companion.agent import approval_display

SOURCE = Path(__file__).parent / "fixtures" / "casespec_source_massflow.json"


def _spec(thermal: dict):
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    raw["thermal"] = thermal
    return case_spec.normalize_case_spec(raw)


AMBIENT = {
    "model": "ambient_h_given",
    "ambient_temperature_c": 4.0,
    "outer_heat_transfer_coefficient_w_m2k": 6.5,
    "wall": {"thickness_m": 0.0127, "material": {"conductivity_w_mk": 45.0, "heat_capacity_j_kgk": 470.0, "density_kg_m3": 7850.0}},
}


def _thermal_rows(spec, locale):
    group = "열전달" if locale == "ko" else "Heat transfer"
    return [(row["name"], row["value"], row["unit"]) for row in approval_display.reviewed_inputs(spec, locale=locale) if row["group"] == group]


def test_ambient_thermal_values_are_on_the_card_in_english():
    assert _thermal_rows(_spec(AMBIENT), "en") == [
        ("Model", "Ambient (given h)", ""),
        ("Ambient temperature", "4", "°C"),
        ("Outer heat transfer coefficient", "6.5", "W/m²K"),
        ("Wall thickness", "0.0127", "m"),
        ("Wall conductivity", "45", "W/m·K"),
        ("Wall heat capacity", "470", "J/kg·K"),
        ("Wall density", "7850", "kg/m³"),
    ]


def test_ambient_thermal_values_are_on_the_card_in_korean():
    rows = _thermal_rows(_spec(AMBIENT), "ko")
    assert rows[0] == ("모델", "주변 열전달(h 지정)", "")
    assert ("주변 온도", "4", "°C") in rows
    assert ("벽 두께", "0.0127", "m") in rows
    assert len(rows) == 7


def test_adiabatic_is_stated_on_the_card():
    assert _thermal_rows(_spec({"model": "adiabatic"}), "en") == [("Model", "Adiabatic", "")]
    assert _thermal_rows(_spec({"model": "adiabatic"}), "ko") == [("모델", "단열", "")]
