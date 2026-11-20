"""Boundary values said in chat reach the draft without editing the table.

Live PVT 2026-11-16 (hr01): an engineer gave "WA 12 bar, WB 11 bar, 40 C, SEP 8 bar"
in chat for a table with pipe rows only. The import could not take them, so the
assistant sent the engineer back to Excel to add node rows. `boundaries` now carries
those values as node rows of the draft. A node the table already has a row for, or a
node the table does not have, is refused by name.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from olga_companion import case_draft_store
from olga_companion.agent import approvals, tools
from olga_companion.agent.pipe_table_schemas import PIPE_TABLE_PARAMETER_SCHEMAS
from olga_companion.agent.tools import ToolError

_TESTS = Path(__file__).parent
_PIPES_ONLY = (
    "Line,From,To,Length (m),Elevation (m),Diameter (mm),Roughness (mm)\n"
    "WELL_A,WA,J1,500,-5,150,0.045\n"
    "WELL_B,WB,J1,600,10,150,0.045\n"
    "TRUNK,J1,SEP,1500,25,250,0.045\n"
)
_SAID = [
    {"node": "WA", "kind": "source", "pressure_pa": 1_200_000, "temperature_c": 40,
     "gas_fraction": 1.0, "water_fraction": 0.9},
    {"node": "WB", "kind": "source", "pressure_pa": 1_100_000, "temperature_c": 40,
     "gas_fraction": 1.0, "water_fraction": 0.9},
    {"node": "SEP", "kind": "sink", "pressure_pa": 800_000, "temperature_c": 30,
     "gas_fraction": 1.0, "water_fraction": 0.9},
]


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    shutil.copyfile(_TESTS / "fixtures" / "fluids" / "fluid.tab", workspace_root / "fluid.tab")
    (workspace_root / "gathering.csv").write_text(_PIPES_ONLY, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(tmp_path / "drafts"))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    approvals.revoke_all()
    yield workspace_root
    approvals.revoke_all()


def _import(**override) -> dict:
    args = {
        "path": "gathering.csv", "pvt_reference": "fluid.tab", "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"}, "end_time_s": 600, **override,
    }
    return tools.dispatch("pipe_table_import", args)


def test_the_schema_takes_boundaries() -> None:
    props = PIPE_TABLE_PARAMETER_SCHEMAS["pipe_table_import"]["properties"]
    item = props["boundaries"]["items"]
    assert item["required"] == ["node", "kind"]
    assert item["properties"]["kind"]["enum"] == ["source", "sink", "closed"]
    assert {"pressure_pa", "temperature_c", "gas_fraction", "water_fraction", "mass_flow_kg_s"} <= set(item["properties"])


def test_without_boundaries_the_ends_are_still_missing(root: Path) -> None:
    result = _import()
    assert result["created"] is False
    assert {issue["code"] for issue in result["issues"]} >= {"missing_boundary_row"}


def test_boundaries_said_in_chat_make_the_draft(root: Path) -> None:
    result = _import(boundaries=_SAID)
    assert result["created"] is True, result.get("issues")
    by_node = {item["node"]: item for item in result["boundaries"]}
    assert set(by_node) == {"WA", "WB", "SEP"}
    assert by_node["WA"]["pressure_bar"] == 12 and by_node["SEP"]["kind"] == "sink"
    draft = case_draft_store.get_draft(result["draft_id"], context_generation=0)
    pressures = sorted(round(node["pressure_pa"]) for node in draft.spec["nodes"] if "pressure_pa" in node)
    assert pressures == [800_000, 1_100_000, 1_200_000]


def test_chat_boundaries_survive_a_draft_edit(root: Path) -> None:
    result = _import(boundaries=_SAID)
    edited = tools.dispatch("case_draft_edit", {
        "draft_id": result["draft_id"], "revision": result["revision"],
        "ops": [{"op": "set_end_time", "end_time_s": 1200}],
    })
    assert edited["revision"] == result["revision"] + 1


def test_a_node_the_table_does_not_have_is_refused_by_name(root: Path) -> None:
    wrong = [*_SAID[:2], {**_SAID[2], "node": "SEPARATOR"}]
    with pytest.raises(ToolError, match="SEPARATOR"):
        _import(boundaries=wrong)


def test_a_node_given_twice_in_chat_is_refused(root: Path) -> None:
    with pytest.raises(ToolError, match="WA"):
        _import(boundaries=[*_SAID, _SAID[0]])


def test_a_table_row_and_a_chat_value_for_one_node_is_refused(root: Path) -> None:
    (root / "gathering.csv").write_text(
        _PIPES_ONLY.replace("Roughness (mm)\n", "Roughness (mm),Node,Node kind,Pressure (bar),Temperature (C),Gas fraction,Water fraction\n")
        .replace("0.045\n", "0.045,,,,,,\n")
        + ",,,,,,,SEP,sink,8,30,1,0.9\n",
        encoding="utf-8",
    )
    result = _import(boundaries=_SAID)
    assert result["created"] is False
    assert "duplicate_boundary_row" in {issue["code"] for issue in result["issues"]}



# Live PVT 2026-11-16 (hr01): asked to turn OLGA's steady-state pre-processor on, the
# assistant could only change a sandbox copy that could be neither saved nor run.
def test_the_steady_state_switch_is_a_draft_edit(root: Path) -> None:
    result = _import(boundaries=_SAID)
    draft = case_draft_store.get_draft(result["draft_id"], context_generation=0)
    assert draft.spec["integration"]["steady_state"] is False
    assert "initial_conditions" in draft.spec

    on = tools.dispatch("case_draft_edit", {
        "draft_id": result["draft_id"], "revision": result["revision"],
        "ops": [{"op": "set_steady_state", "steady_state": True}],
    })
    draft = case_draft_store.get_draft(result["draft_id"], context_generation=0)
    assert "steady_state" not in draft.spec["integration"]
    assert "initial_conditions" not in draft.spec

    tools.dispatch("case_draft_edit", {
        "draft_id": result["draft_id"], "revision": on["revision"],
        "ops": [{"op": "set_steady_state", "steady_state": False}],
    })
    draft = case_draft_store.get_draft(result["draft_id"], context_generation=0)
    assert draft.spec["integration"]["steady_state"] is False
    assert "initial_conditions" in draft.spec
