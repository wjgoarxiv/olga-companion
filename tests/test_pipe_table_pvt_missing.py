"""A pipe-table import names a PVT table that is not there yet.

Live PVT 2026-11-16 (hr01): the import took `fluids/air_water.tab`, which did not exist,
and the engineer learned it only at the save plan. The import now says so at once, but
still makes the draft: a table that a later plan step generates is absent at import too.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from olga_companion.agent import approvals, tools

_TESTS = Path(__file__).parent
_TABLE = (
    "Line,From,To,Length (m),Elevation (m),Diameter (mm),Roughness (mm)\n"
    "MAIN,S,T,500,0,150,0.045\n"
)
_ENDS = [
    {"node": "S", "kind": "source", "pressure_pa": 1_200_000, "temperature_c": 40, "gas_fraction": 1.0, "water_fraction": 0.5},
    {"node": "T", "kind": "sink", "pressure_pa": 800_000, "temperature_c": 30, "gas_fraction": 1.0, "water_fraction": 0.5},
]


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    (workspace_root / "lines").mkdir(parents=True)
    (workspace_root / "lines" / "pipes.csv").write_text(_TABLE, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(tmp_path / "drafts"))
    approvals.revoke_all()
    yield workspace_root
    approvals.revoke_all()


def _import(reference: str) -> dict:
    return tools.dispatch("pipe_table_import", {
        "path": "lines/pipes.csv", "pvt_reference": reference, "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"}, "end_time_s": 600, "boundaries": _ENDS,
    })


def test_a_missing_table_is_named_but_the_draft_is_made(root: Path) -> None:
    result = _import("fluids/air_water.tab")
    assert result["created"] is True
    assert result["pvt_missing"] == {"reference": "fluids/air_water.tab"}


def test_a_reference_that_climbs_out_is_refused_before_any_lookup(root: Path) -> None:
    shutil.copyfile(_TESTS / "fixtures" / "fluids" / "fluid.tab", root.parent / "outside.tab")
    result = _import("../outside.tab")
    assert result["created"] is False
    assert [issue["code"] for issue in result["issues"]] == ["spec.invalid_pvt_reference"]


@pytest.mark.parametrize("where",["fluid.tab", "lines/fluid.tab"])
def test_a_table_at_the_root_or_beside_the_pipe_table_is_found(root: Path, where: str) -> None:
    shutil.copyfile(_TESTS / "fixtures" / "fluids" / "fluid.tab", root / where)
    result = _import("fluid.tab")
    assert result["created"] is True
    assert "pvt_missing" not in result
