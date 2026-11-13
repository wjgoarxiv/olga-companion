"""The bundled generic air-water table as an approval-gated agent tool.

Offline. The table the tool copies is a small stand-in placed where the build looks for the
real one, except for the one test that checks the real bundled file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from olga_companion import fluid_table, starter_fluids, workspace
from olga_companion.agent import (
    approval_display,
    approval_execution,
    approvals,
    history,
    pending_approvals,
    plan_model,
    session_token,
    tools,
)
from olga_companion.agent.tool_validation import ToolError, ToolRefusedError

TOOL = "fluids_starter_tab"
FIXTURES = Path(__file__).parent / "fixtures" / "fluids"
REPO = Path(__file__).resolve().parents[1]
SCHEMA_LIMIT = 4096


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "workspace"
    root.mkdir()
    fluids = tmp_path / "bundle" / "fluids"
    fluids.mkdir(parents=True)
    stand_in = (FIXTURES / "standard_three.tab").read_text(encoding="utf-8").replace("FLUID-A", "AIR_WATER")
    (fluids / starter_fluids.TABLE_NAME).write_text(stand_in, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(starter_fluids, "bundled_table", lambda: fluids / starter_fluids.TABLE_NAME)
    session_token.boot_token()
    pending_approvals.revoke_all()
    yield root
    pending_approvals.revoke_all()


@pytest.fixture
def bundled() -> Path:
    return starter_fluids.bundled_table()


@pytest.fixture
def root(_workspace: Path) -> Path:
    return _workspace


@pytest.fixture
def gen() -> int:
    return workspace.context_generation()


def _approved(args: dict[str, Any], generation: int) -> dict[str, Any]:
    payload = tools.approval_payload(TOOL, args)
    token = approvals.mint(TOOL, payload, context_generation=generation)["token"]
    return {**args, "approval_token": token, "idempotency_key": "k" * 32}


# ------------------------------------------------------------------ the tool


def test_the_tool_is_a_closed_approval_gated_side_effect_in_every_build() -> None:
    tool = tools.TOOLS[TOOL]
    assert tool.side_effect is True
    assert tool.parameters["additionalProperties"] is False
    assert set(tool.parameters["properties"]) == {"tab_rel", "approval_token", "idempotency_key"}
    assert set(tool.parameters["required"]) == {"tab_rel", "approval_token", "idempotency_key"}
    spec = next(item for item in tools.tool_specs() if item["name"] == TOOL)
    assert "approval_token" not in spec["parameters"]["properties"]
    assert "idempotency_key" not in spec["parameters"]["required"]


def test_the_tool_schema_stays_inside_the_per_tool_budget() -> None:
    spec = next(item for item in tools.tool_specs() if item["name"] == TOOL)
    assert len(json.dumps(spec)) <= SCHEMA_LIMIT


def test_the_tool_never_joins_a_plan() -> None:
    assert TOOL in plan_model.NEVER_IN_PLAN
    with pytest.raises(ToolError, match=TOOL):
        tools.approval_payload("action_plan", {"steps": [{"kind": TOOL, "args": {"tab_rel": "a.tab"}}]})


def test_dispatch_copies_the_bundled_table_to_a_new_file(root: Path, gen: int) -> None:
    bundled = starter_fluids.bundled_table()
    result = tools.dispatch(TOOL, _approved({"tab_rel": "air_water.tab"}, gen))

    target = root / "air_water.tab"
    assert target.read_bytes() == bundled.read_bytes()
    assert result["ok"] is True
    assert result["tab_rel"] == "air_water.tab"
    assert result["fluid_label"] == "AIR_WATER" == starter_fluids.LABEL
    assert result["validator"]["valid"] is True
    assert fluid_table.pickup_tab(str(target), "AIR_WATER")["valid"] is True
    assert "approval_token" not in json.dumps(result)


def test_dispatch_works_in_a_subfolder_the_workspace_already_has(root: Path, gen: int) -> None:
    (root / "fluids").mkdir()
    result = tools.dispatch(TOOL, _approved({"tab_rel": "fluids/air_water.tab"}, gen))
    assert result["tab_rel"] == "fluids/air_water.tab"
    assert (root / "fluids" / "air_water.tab").is_file()


def test_an_existing_file_is_refused_and_left_untouched(root: Path) -> None:
    (root / "air_water.tab").write_text("owner file\n", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        tools.approval_payload(TOOL, {"tab_rel": "air_water.tab"})
    assert (root / "air_water.tab").read_text(encoding="utf-8") == "owner file\n"


def test_a_file_that_appears_after_the_card_is_never_overwritten(root: Path, gen: int) -> None:
    approved = _approved({"tab_rel": "air_water.tab"}, gen)
    (root / "air_water.tab").write_text("owner file\n", encoding="utf-8")
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, approved)
    assert (root / "air_water.tab").read_text(encoding="utf-8") == "owner file\n"


@pytest.mark.parametrize("tab_rel", ["../outside.tab", "/tmp/outside.tab", "sub/../../outside.tab"])
def test_a_destination_outside_the_workspace_is_refused(root: Path, tab_rel: str) -> None:
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, {"tab_rel": tab_rel})
    assert not (root.parent / "outside.tab").exists()


def test_a_symlink_that_leaves_the_workspace_is_refused(root: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        os.symlink(elsewhere, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable here")
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, {"tab_rel": "link/air_water.tab"})
    assert not (elsewhere / "air_water.tab").exists()


@pytest.mark.parametrize("tab_rel", ["air_water.txt", "air_water", "air_water.mfl", ""])
def test_only_a_tab_destination_in_an_existing_folder_is_accepted(root: Path, tab_rel: str) -> None:
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, {"tab_rel": tab_rel})


def test_a_missing_folder_is_refused_without_creating_it(root: Path) -> None:
    with pytest.raises(ToolError, match="folder"):
        tools.approval_payload(TOOL, {"tab_rel": "nope/air_water.tab"})
    assert not (root / "nope").exists()


def test_a_build_without_the_bundled_table_refuses_before_any_card(root: Path, bundled: Path) -> None:
    bundled.unlink()
    with pytest.raises(ToolError, match="not included"):
        tools.approval_payload(TOOL, {"tab_rel": "air_water.tab"})
    assert not (root / "air_water.tab").exists()


def test_a_bundled_table_the_validator_rejects_writes_nothing(root: Path, bundled: Path, gen: int) -> None:
    approved = _approved({"tab_rel": "air_water.tab"}, gen)
    bundled.write_text("not a table\n", encoding="utf-8")
    with pytest.raises(ToolRefusedError):
        tools.dispatch(TOOL, approved)
    assert not (root / "air_water.tab").exists()


def test_the_approval_is_single_use(root: Path, gen: int) -> None:
    approved = _approved({"tab_rel": "air_water.tab"}, gen)
    tools.dispatch(TOOL, approved)
    (root / "air_water.tab").unlink()
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, approved)
    assert not (root / "air_water.tab").exists()


def test_the_handler_needs_a_server_capability(root: Path) -> None:
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, {"tab_rel": "air_water.tab"})
    assert not (root / "air_water.tab").exists()


def test_one_card_click_copies_the_table_through_the_real_approval_route(root: Path, gen: int) -> None:
    session_id = history.new_session("starter")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args={"tab_rel": "air_water.tab"}, call_id="s-1",
        context_generation=gen, session_id=session_id,
    )
    body = approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="s-1", context_generation=gen
    )
    assert (root / "air_water.tab").is_file()
    assert body["result"]["validator"]["valid"] is True


# ------------------------------------------------------------------ the card


def test_the_card_says_plainly_it_is_a_generic_air_water_table_in_english(root: Path) -> None:
    shown = approval_display.build(TOOL, {"tab_rel": "air_water.tab"}, locale="en")
    rows = {row["key"]: row for row in shown["fields"]}

    assert rows["file"]["value"] == "air_water.tab"
    assert rows["label"]["value"] == "AIR_WATER"
    assert rows["model"]["value"] == "CPA"
    assert (rows["temperature_range"]["value"], rows["temperature_range"]["unit"]) == ("0 – 80", "degC")
    assert (rows["pressure_range"]["value"], rows["pressure_range"]["unit"]) == ("0.5 – 20", "bar")
    kind = rows["table_kind"]["value"]
    assert "generic air-water table" in kind.casefold()
    assert "CPA" in kind and "0–80" in kind and "0.5–20 bar" in kind
    assert "approval_token" not in json.dumps(shown)


def test_the_card_is_natural_korean_for_a_korean_locale(root: Path) -> None:
    shown = approval_display.build(TOOL, {"tab_rel": "air_water.tab"}, locale="ko")
    kind = next(row["value"] for row in shown["fields"] if row["key"] == "table_kind")
    assert "범용 공기-물 표" in kind
    assert "CPA" in kind and "0–80" in kind and "0.5–20 bar" in kind
    assert "generic" not in kind.casefold()


def test_the_card_is_refused_for_the_same_destinations_the_tool_refuses(root: Path) -> None:
    (root / "air_water.tab").write_text("owner file\n", encoding="utf-8")
    with pytest.raises(ToolError):
        approval_display.build(TOOL, {"tab_rel": "air_water.tab"}, locale="en")


# ------------------------------------------------------- the real bundled file


def test_the_bundle_looks_for_the_table_beside_the_toolkit_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.undo()
    monkeypatch.setenv("OLGA_TOOLKIT_DIR", str(tmp_path / "resources" / "olga-toolkit"))
    assert starter_fluids.bundled_table() == tmp_path / "resources" / "fluids" / "air_water_cpa.tab"


def test_the_real_bundled_table_is_a_valid_three_phase_cpa_air_water_table() -> None:
    table = REPO / "resources" / "fluids" / starter_fluids.TABLE_NAME
    assert table.is_file(), "the generic air-water table has not been produced yet"
    check = fluid_table.pickup_tab(str(table), "AIR_WATER")
    assert check["valid"] is True, check["errors"]
    head = table.read_text(encoding="utf-8").split("PVTTABLE POINT", 1)[0]
    assert "PHASE = THREE" in head
    assert "COMPONENTS = ( WATER , NITROGEN , OXYGEN )" in head
    assert "using HA for aqueous phase" in head
    # At 25 C and 1 atm the aqueous phase is liquid water and the gas is air.
    point = next(
        line for line in table.read_text(encoding="utf-8").splitlines()
        if line.startswith("PVTTABLE POINT = ( 101325.000 , 25.0000000 ,")
    )
    values = [float(value) for value in point.split("(", 1)[1].rstrip(") ").split(",")]
    gas_density, water_density = values[2], values[4]
    assert 990 < water_density < 1005
    assert 1.0 < gas_density < 1.3
    assert (REPO / "resources" / "fluids" / "air_water_cpa.mfl").is_file()
