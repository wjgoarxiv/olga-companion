"""Explicit CaseSpec v2 physical inputs for tests.

These are test data. The product has no defaults for any of them: every value must be
stated by the user, so fixtures state them here instead of relying on compiler guesses.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

FLUID_LABEL = "TEST_FLUID"
PVT_TABLE_TEXT = f'PVTTABLE LABEL = "{FLUID_LABEL}", PHASE = BOTH\n'
SOURCE_TEMPERATURE_C = 40.0
SINK_TEMPERATURE_C = 30.0
# Sample phase fractions for tests. The product does not fill these in.
SOURCE_GAS_FRACTION = 0.2
SOURCE_WATER_FRACTION = 0.4
SINK_GAS_FRACTION = 0.15
SINK_WATER_FRACTION = 0.35
ROUGHNESS_M = 5e-5
ADIABATIC: dict[str, Any] = {"model": "adiabatic"}
AMBIENT: dict[str, Any] = {
    "model": "ambient_h_given",
    "ambient_temperature_c": 10.0,
    "outer_heat_transfer_coefficient_w_m2k": 15.0,
    "wall": {
        "thickness_m": 0.01,
        "material": {
            "conductivity_w_mk": 45.0,
            "heat_capacity_j_kgk": 460.0,
            "density_kg_m3": 7850.0,
        },
    },
}


def with_v2_inputs(spec: dict[str, Any], thermal: dict[str, Any] = ADIABATIC) -> dict[str, Any]:
    """Return a copy of a geometry-only spec completed with the v2 physical inputs."""
    upgraded = deepcopy(spec)
    upgraded["version"] = "2"
    upgraded.setdefault("fluid_label", FLUID_LABEL)
    upgraded.setdefault("thermal", deepcopy(thermal))
    for node in upgraded["nodes"]:
        if node["kind"] == "source":
            node.setdefault("temperature_c", SOURCE_TEMPERATURE_C)
            node.setdefault("gas_fraction", SOURCE_GAS_FRACTION)
            node.setdefault("total_water_fraction", SOURCE_WATER_FRACTION)
        elif node["kind"] == "sink":
            node.setdefault("temperature_c", SINK_TEMPERATURE_C)
            node.setdefault("gas_fraction", SINK_GAS_FRACTION)
            node.setdefault("total_water_fraction", SINK_WATER_FRACTION)
    for flowpath in upgraded["flowpaths"]:
        for pipe in flowpath["pipes"]:
            pipe.setdefault("roughness_m", ROUGHNESS_M)
    return upgraded
