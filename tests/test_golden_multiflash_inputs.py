"""R4 and R10: Multiflash table inputs and load errors are checked before a table is accepted."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from olga_companion import fluid_table, fluids
from olga_companion import multiflash_direct as md
from olga_companion.fluid_table import FluidTableError

from test_multiflash_direct import FIX, _workspace


def test_r4_a_load_error_refuses_the_table(tmp_path: Path) -> None:
    mfl = _workspace(tmp_path)

    def engine(request: dict[str, Any]) -> dict[str, Any]:
        table = (FIX / "handwritten_3x3.tab").read_text(encoding="utf-8")
        Path(request["tab_path"]).write_text(table.replace("LABEL = probe", f"LABEL = {request['title']}", 1), encoding="utf-8")
        return {"ok": True, "errors": [], "load_errors": [20575]}

    with pytest.raises(FluidTableError, match="could not read gas_water.mfl"):
        md.make_tab(str(mfl), None, engine=engine, error_file=FIX / "mini.err")
    assert sorted(p.name for p in mfl.parent.iterdir()) == ["gas_water.mfl"]


def test_r4_a_table_changing_during_pickup_is_not_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tab = tmp_path / "f.tab"
    tab.write_text("start", encoding="utf-8")

    def growing(path: str) -> dict[str, Any]:
        Path(path).write_text("start and more", encoding="utf-8")
        return {"valid": True}

    monkeypatch.setattr(fluids, "inspect_tab", growing)
    result = fluid_table.pickup_tab(str(tab))
    assert result["valid"] is False
    assert "still being written" in result["errors"][0]["message"]


def test_r10_two_names_for_one_component_are_refused() -> None:
    names = {"METHANE": "METHANE", "C1": "METHANE", "WATER": "WATER"}
    with pytest.raises(FluidTableError, match="same databank component"):
        fluid_table.validate_composition(
            [{"name": "methane", "mole_fraction": 0.4}, {"name": "C1", "mole_fraction": 0.4},
             {"name": "WATER", "mole_fraction": 0.2}],
            names,
        )


@pytest.mark.parametrize("grid", [[150.0, 20.0, 50.0], [10.0, 10.0, 20.0]])
def test_r10_grids_must_increase(grid: list[float]) -> None:
    with pytest.raises(FluidTableError, match="strictly increasing"):
        fluid_table.validate_grid(grid, "temperature")


def _gas_water() -> str:
    return (FIX / "gas_water.mfl").read_text(encoding="utf-8")


def test_r10_make_table_refuses_an_unsorted_mfl_grid() -> None:
    text = _gas_water().replace("temperatures 260 300\n  340 ;", "temperatures 340 260 300 ;")
    with pytest.raises(FluidTableError, match="strictly increasing"):
        md.read_table_request(text)


def test_r10_make_table_refuses_a_repeated_mfl_grid_point() -> None:
    text = _gas_water().replace("pressures\n  50000 1000000 5000000", "pressures 50000 50000 5000000")
    with pytest.raises(FluidTableError, match="strictly increasing"):
        md.read_table_request(text)


def test_r10_make_table_refuses_a_component_listed_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fluid_table, "databank_names", lambda: {"METHANE": "METHANE", "C1": "METHANE"})
    text = _gas_water().replace("2 ETHANE", "2 C1")
    with pytest.raises(FluidTableError, match="same component"):
        md.read_table_request(text)
