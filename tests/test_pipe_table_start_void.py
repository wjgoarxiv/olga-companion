"""The start void of a table case is the inlet gas VOLUME share, not the gas mass share.

Hand check used below (grid node 10 bar, 30 C of start_void_standard.tab: ROG 10, ROHL 800,
ROWT 1000 kg/m3), inlet gas share 0.5 of gas+oil and 0.2 water of the whole mixture:
gas mass 0.5*(1-0.2)=0.4, oil mass 0.4, water mass 0.2, so volumes 0.4/10=0.04,
0.4/800=0.0005 and 0.2/1000=0.0002 m3 per kg; void = 0.04/0.0407 = 0.982801.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from olga_companion.pipe_table import read_table
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

FLUIDS = Path(__file__).parent / "fixtures" / "fluids"
R_GAS = 8.314462618


def _table(tmp_path: Path, gas: float, water: float, pressure_bar: float = 10.0, temperature_c: float = 30.0) -> Path:
    path = tmp_path / "pipes.csv"
    path.write_text(
        "flowpath,pipe,from_node,to_node,length_m,elevation_m,inner_diameter_m,roughness_m,"
        "node,node_kind,pressure_bar,temperature_c,gas_fraction,water_fraction\n"
        f",,,,,,,,SRC,source,{pressure_bar},{temperature_c},{gas},{water}\n"
        f",,,,,,,,SNK,sink,{pressure_bar},{temperature_c},{gas},{water}\n"
        "FP_A,P1,SRC,SNK,10.0,0.0,0.05,5e-05,,,,,,\n",
        encoding="utf-8",
    )
    return path


def _void(tmp_path: Path, gas: float, water: float, *, tab_dir: Path | None = None, **state: float) -> float:
    options = ImportOptions(
        pvt_reference="start_void_standard.tab", fluid_label="FLUID-V", thermal={"model": "adiabatic"},
        end_time_s=60.0, pvt_search_dirs=(str(tab_dir),) if tab_dir else (),
    )
    result = build_case_spec(read_table(_table(tmp_path, gas, water, **state)), options)
    assert result.issues == (), result.issues
    return result.spec["initial_conditions"]["void_fraction"]


def _with_tab(tmp_path: Path) -> Path:
    folder = tmp_path / "fluids"
    folder.mkdir()
    shutil.copyfile(FLUIDS / "start_void_standard.tab", folder / "start_void_standard.tab")
    return folder


def test_a_gas_only_inlet_keeps_a_void_of_exactly_one(tmp_path: Path) -> None:
    assert _void(tmp_path, 1.0, 0.0) == 1.0
    assert _void(tmp_path, 1.0, 0.0, tab_dir=_with_tab(tmp_path)) == 1.0


def test_a_wet_inlet_uses_the_table_densities_at_the_start_state(tmp_path: Path) -> None:
    void = _void(tmp_path, 0.5, 0.2, tab_dir=_with_tab(tmp_path))

    assert void == pytest.approx(0.04 / 0.0407, abs=1e-6)
    assert void == pytest.approx(0.982801, abs=1e-6)


def test_between_grid_nodes_the_table_densities_are_interpolated(tmp_path: Path) -> None:
    # 5.5 bar, 20 C is the middle of the grid: ROG (1+1+11+10)/4, ROHL 795, ROWT 1000.
    void = _void(tmp_path, 0.5, 0.2, tab_dir=_with_tab(tmp_path), pressure_bar=5.5, temperature_c=20.0)

    gas, oil, water = 0.4 / 5.75, 0.4 / 795.0, 0.2 / 1000.0
    assert void == pytest.approx(gas / (gas + oil + water), abs=1e-6)


def test_a_missing_table_falls_back_to_ideal_gas_and_1000_kg_m3_liquid(tmp_path: Path) -> None:
    # Default gas molar mass 0.02896 kg/mol at 10 bar and 30 C.
    rho_gas = 1_000_000.0 * 0.02896 / (R_GAS * 303.15)
    gas, liquid = 0.4 / rho_gas, 0.4 / 1000.0 + 0.2 / 1000.0

    assert _void(tmp_path, 0.5, 0.2) == pytest.approx(gas / (gas + liquid), abs=1e-6)
    # A search folder with no table in it behaves the same way.
    assert _void(tmp_path, 0.5, 0.2, tab_dir=tmp_path) == pytest.approx(gas / (gas + liquid), abs=1e-6)


def test_an_unreadable_table_falls_back_to_ideal_gas(tmp_path: Path) -> None:
    folder = tmp_path / "fluids"
    folder.mkdir()
    shutil.copyfile(FLUIDS / "broken.tab", folder / "start_void_standard.tab")

    assert _void(tmp_path, 0.5, 0.2, tab_dir=folder) == pytest.approx(_void(tmp_path, 0.5, 0.2), abs=1e-12)


@pytest.mark.parametrize("gas", [0.0, 0.001, 0.01, 0.3, 0.999, 1.0])
@pytest.mark.parametrize("water", [0.0, 0.5, 1.0])
def test_the_void_stays_within_zero_and_one(tmp_path: Path, gas: float, water: float) -> None:
    for tab_dir in (None, _with_tab(tmp_path)):
        assert 0.0 <= _void(tmp_path, gas, water, tab_dir=tab_dir) <= 1.0


def test_a_small_gas_mass_share_gives_a_far_larger_volume_share(tmp_path: Path) -> None:
    # Today's value would be the mass share 0.01. Here gas is 0.01/10 = 0.001 and oil 0.99/800 = 0.0012375 m3 per kg.
    assert _void(tmp_path, 0.01, 0.0, tab_dir=_with_tab(tmp_path)) == pytest.approx(0.001 / 0.0022375, abs=1e-6)


def test_the_same_inputs_give_the_same_case_digest(tmp_path: Path) -> None:
    folder = _with_tab(tmp_path)
    options = ImportOptions(
        pvt_reference="start_void_standard.tab", fluid_label="FLUID-V", thermal={"model": "adiabatic"},
        end_time_s=60.0, pvt_search_dirs=(str(folder),),
    )
    digests = {
        hashlib.sha256(json.dumps(
            build_case_spec(read_table(_table(tmp_path, 0.5, 0.2)), options).spec, sort_keys=True,
        ).encode()).hexdigest()
        for _ in range(2)
    }
    assert len(digests) == 1


class _Parsed:
    """A STANDARD table whose axes are in the file's own units (BAR and K), as _density_at must convert."""

    columns = ["PT", "TM", "ROG"]
    pressure_grid = [1.0, 10.0]  # bar
    temperature_grid = [283.15, 303.15]  # K = 10 C, 30 C
    point_rows = [[1.0, 283.15, 1.0], [1.0, 303.15, 1.0], [10.0, 283.15, 11.0], [10.0, 303.15, 10.0]]
    _pairs = {"PRESSURE": {"unit": "BAR"}, "TEMPERATURE": {"unit": "K"}}


def test_a_table_in_bar_and_kelvin_is_looked_up_in_pa_and_celsius() -> None:
    from olga_companion.pipe_table_import import _density_at

    # The middle of the grid, 5.5 bar and 20 C, is (1+1+11+10)/4; unconverted it would clamp to an edge node.
    assert _density_at(_Parsed, "ROG", 550_000.0, 20.0) == pytest.approx(5.75)
    assert _density_at(_Parsed, "ROG", 1_000_000.0, 30.0) == pytest.approx(10.0)
    assert _density_at(_Parsed, "ROG", 100_000.0, 10.0) == pytest.approx(1.0)


def test_a_table_with_an_unknown_axis_unit_gives_no_density() -> None:
    from olga_companion.pipe_table_import import _density_at

    unknown = type("Unknown", (_Parsed,), {"_pairs": {"PRESSURE": {"unit": "PSI"}, "TEMPERATURE": {"unit": "K"}}})

    assert _density_at(unknown, "ROG", 550_000.0, 20.0) is None
