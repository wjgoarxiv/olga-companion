"""Chat path from a pipe table to a publish approval: import, review, edit, plan from a draft."""

from __future__ import annotations

import json
import math
import shutil
import types
from pathlib import Path

import pytest

from olga_companion import case_draft_store, config
from olga_companion.agent import approvals, case_publish_adapter, plan_model, tools
from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient

_TESTS = Path(__file__).parent
_TABLES = _TESTS / "fixtures" / "pipe_tables"
_NEW_TOOLS = ("pipe_table_import", "case_draft_review", "case_draft_edit")
_RESULT_LIMIT = 16384
_CATALOG_LIMIT = 140 * 1024
_TOOL_LIMIT = 4 * 1024


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    shutil.copyfile(_TESTS / "fixtures" / "fluids" / "fluid.tab", workspace_root / "fluid.tab")
    for table in _TABLES.glob("*.csv"):
        shutil.copyfile(table, workspace_root / table.name)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(tmp_path / "drafts"))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(tmp_path / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(tmp_path / "journal"))
    approvals.revoke_all()
    yield workspace_root
    approvals.revoke_all()


def _import(name: str = "small_branch.csv", **override) -> dict:
    args = {
        "path": name,
        "pvt_reference": "fluid.tab",
        "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"},
        "end_time_s": 600,
        **override,
    }
    return tools.dispatch("pipe_table_import", args)


def _size(result: dict) -> int:
    return len(json.dumps(result, ensure_ascii=False))


def _pipes_lists(value) -> list[list]:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "pipes" and isinstance(item, list):
                found.append(item)
            found.extend(_pipes_lists(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_pipes_lists(item))
    return found


def _stored(draft_id: str):
    return case_draft_store.get_draft(draft_id, context_generation=0)


def test_import_of_the_synthetic_network_is_a_bounded_summary_with_a_draft_id(root: Path) -> None:
    result = _import("synthetic_network.csv")

    assert result["created"] is True
    assert len(result["draft_id"]) == 32
    assert result["revision"] == 1
    assert result["counts"]["flowpaths"] == 317
    assert result["caps"]["sections"]["value"] == result["counts"]["sections"]
    assert result["caps"]["sections"]["limit"] >= result["counts"]["sections"]
    assert {"shortest_section_m", "longest_section_m", "worst_ratio_in_flowpaths"} <= set(
        result["section_stats"]
    )
    assert isinstance(result["junction_warning_count"], int)
    assert _size(result) < _RESULT_LIMIT
    assert "spec" not in result
    assert not (root / ".casespec-owner.genkey").exists()


def test_a_table_with_problems_makes_no_draft_and_names_the_first_issues(
    root: Path, tmp_path: Path
) -> None:
    lines = (_TABLES / "small_branch.csv").read_text(encoding="utf-8").splitlines()
    (root / "broken.csv").write_text("\n".join(lines[:4] + [lines[4].replace("20.0", "")]), encoding="utf-8")

    result = _import("broken.csv")

    assert result["created"] is False
    assert 1 <= len(result["issues"]) <= 20
    assert result["issue_count"] >= 1
    assert "draft_id" not in result
    assert not list((tmp_path / "drafts").glob("*.json"))


def test_physical_inputs_are_required_and_never_defaulted(root: Path) -> None:
    for missing in ("pvt_reference", "fluid_label", "thermal", "end_time_s"):
        args = {
            "path": "small_branch.csv",
            "pvt_reference": "fluid.tab",
            "fluid_label": "FLUID-A",
            "thermal": {"model": "adiabatic"},
            "end_time_s": 600,
        }
        del args[missing]
        with pytest.raises(tools.ToolError, match=missing):
            tools.dispatch("pipe_table_import", args)


def test_only_csv_and_xlsx_inside_the_workspace_are_read(root: Path, tmp_path: Path) -> None:
    (root / "table.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    shutil.copyfile(_TABLES / "small_branch.csv", outside)

    with pytest.raises(tools.ToolError, match="extension"):
        _import("table.txt")
    with pytest.raises(tools.ToolError, match="inside the workspace"):
        _import(str(outside))
    with pytest.raises(tools.ToolError, match="extension"):
        tools.dispatch("genkey_review", {"path": "small_branch.csv"})


def test_review_pages_the_flowpaths_fifty_at_a_time(root: Path) -> None:
    draft_id = _import("synthetic_network.csv")["draft_id"]

    first = tools.dispatch("case_draft_review", {"draft_id": draft_id})
    last = tools.dispatch("case_draft_review", {"draft_id": draft_id, "page": 7})

    assert first["page"] == 1 and first["pages"] == 7
    assert len(first["flowpaths"]) == 50
    assert len(last["flowpaths"]) == 317 - 6 * 50
    assert first["flowpaths"][0] == {
        "label": "FP_001",
        "source_name": "SUPPLY",
        "pipes": 3,
        "sections": first["flowpaths"][0]["sections"],
        "from": "SRC_001",
        "to": first["flowpaths"][0]["to"],
    }
    assert _size(first) < _RESULT_LIMIT and _size(last) < _RESULT_LIMIT
    with pytest.raises(tools.ToolError, match="page"):
        tools.dispatch("case_draft_review", {"draft_id": draft_id, "page": 8})


def test_resegment_changes_the_section_statistics(root: Path) -> None:
    before = _import("synthetic_network.csv")

    after = tools.dispatch(
        "case_draft_edit",
        {"draft_id": before["draft_id"], "revision": 1, "ops": [{"op": "resegment", "max_section_m": 3.0}]},
    )

    assert after["revision"] == 2
    assert after["counts"]["sections"] < before["counts"]["sections"]
    assert after["section_stats"] != before["section_stats"]
    assert _stored(before["draft_id"]).revision == 2
    assert _size(after) < _RESULT_LIMIT


def test_a_stale_revision_is_refused_and_changes_nothing(root: Path) -> None:
    draft_id = _import()["draft_id"]
    edit = {"draft_id": draft_id, "revision": 1, "ops": [{"op": "set_end_time", "end_time_s": 900}]}
    tools.dispatch("case_draft_edit", edit)

    with pytest.raises(tools.ToolError, match="changed since"):
        tools.dispatch("case_draft_edit", {**edit, "ops": [{"op": "set_end_time", "end_time_s": 1200}]})

    assert _stored(draft_id).revision == 2
    assert _stored(draft_id).spec["integration"]["end_time_s"] == 900


def test_typed_edits_change_the_draft_through_the_importer(root: Path) -> None:
    draft_id = _import()["draft_id"]

    edited = tools.dispatch(
        "case_draft_edit",
        {
            "draft_id": draft_id,
            "revision": 1,
            "ops": [
                {"op": "set_valve_schedule", "valve": "V_FP_A", "schedule": [
                    {"time_s": 0, "opening": 1}, {"time_s": 100, "opening": 0.25}]},
                {"op": "set_boundary", "node": "SNK_001", "pressure_pa": 250000, "temperature_c": 30},
                {"op": "set_end_time", "end_time_s": 1800},
            ],
        },
    )
    spec = _stored(draft_id).spec

    assert edited["revision"] == 2 and len(edited["applied"]) == 3
    assert spec["integration"]["end_time_s"] == 1800
    assert spec["equipment"][0]["schedule"] == [
        {"time_s": 0.0, "opening": 1.0}, {"time_s": 100.0, "opening": 0.25}]
    sink = next(node for node in spec["nodes"] if node["label"] == "SNK_001")
    assert math.isclose(sink["pressure_pa"], 250000) and sink["temperature_c"] == 30

    by_label = tools.dispatch(
        "case_draft_edit",
        {"draft_id": draft_id, "revision": 2, "ops": [
            {"op": "set_valve_schedule", "valve": "V_001", "schedule": [{"time_s": 0, "opening": 0.5}]}]},
    )
    assert by_label["revision"] == 3
    assert "schedule" not in _stored(draft_id).spec["equipment"][0]


def test_an_edit_that_cannot_be_built_leaves_the_draft_unchanged(root: Path) -> None:
    draft_id = _import()["draft_id"]
    for op in (
        {"op": "set_valve_schedule", "valve": "NOPE", "schedule": [{"time_s": 0, "opening": 1}]},
        {"op": "set_boundary", "node": "J_1", "pressure_pa": 200000},
        {"op": "set_boundary", "node": "SRC"},
        {"op": "set_end_time"},
        {"op": "resegment", "max_section_m": 1e-6},
    ):
        with pytest.raises(tools.ToolError):
            tools.dispatch("case_draft_edit", {"draft_id": draft_id, "revision": 1, "ops": [op]})

    assert _stored(draft_id).revision == 1


def _plan(draft_id: str, destination: str = "branch.genkey", **extra) -> dict:
    return tools.dispatch(
        "case_edit_plan",
        {"draft_id": draft_id, "destination_rel": destination, "operations": [], **extra},
    )


def test_plan_from_a_draft_reaches_a_publish_approval_for_a_new_file_only(root: Path) -> None:
    draft_id = _import()["draft_id"]
    tools.dispatch("case_draft_edit", {
        "draft_id": draft_id, "revision": 1, "ops": [{"op": "set_end_time", "end_time_s": 900}]})

    plan = _plan(draft_id)

    assert plan["publishable"] is True and plan["source_kind"] == "case_spec"
    assert not (root / "branch.genkey").exists()
    args = {
        "transaction_id": plan["transaction_id"],
        "source_hash": plan["source_hash"],
        "compiled_hash": plan["compiled_hash"],
        "destination_rel": "branch.genkey",
        "context_generation": plan["context_generation"],
    }
    payload = case_publish_adapter.approval_payload(args)
    assert payload["destination_rel"] == "branch.genkey"
    assert set(payload) == set(args)
    token = approvals.mint("case_publish", payload, context_generation=plan["context_generation"])["token"]
    receipt = tools.dispatch("case_publish", {**args, "approval_token": token, "idempotency_key": "d" * 32})

    published = root / "branch.genkey"
    assert receipt["state"] == "completed" and receipt["destination_rel"] == "branch.genkey"
    assert published.is_file()
    assert sorted(path.name for path in root.glob("*.genkey")) == ["branch.genkey"]
    assert b"ENDTIME=900" in published.read_bytes().replace(b" ", b"")


def test_the_synthetic_network_draft_plans_into_a_publishable_transaction(root: Path) -> None:
    draft_id = _import("synthetic_network.csv")["draft_id"]

    plan = _plan(draft_id, "network.genkey")

    assert plan["publishable"] is True
    assert plan["validation"]["clean"] is True
    assert _size(plan) < _RESULT_LIMIT
    assert not (root / "network.genkey").exists()


def test_plan_from_a_draft_refuses_an_existing_file_and_mixed_sources(root: Path) -> None:
    draft_id = _import()["draft_id"]
    (root / "taken.genkey").write_text("keep\n", encoding="utf-8")

    with pytest.raises(tools.ToolError, match="does not exist"):
        _plan(draft_id, "taken.genkey")
    with pytest.raises(tools.ToolError, match="exactly|additional field"):
        tools.dispatch("case_edit_plan", {
            "draft_id": draft_id, "source": "taken.genkey", "source_hash": "a" * 64,
            "destination_rel": "x.genkey", "operations": [{"op": "set_integration", "end_time_s": 5}]})
    with pytest.raises(tools.ToolError, match="destination_rel|required"):
        tools.dispatch("case_edit_plan", {"draft_id": draft_id, "operations": []})
    with pytest.raises(tools.ToolError, match="draft"):
        _plan("0" * 32)
    assert (root / "taken.genkey").read_text(encoding="utf-8") == "keep\n"


def test_a_workspace_switch_refuses_every_use_of_the_draft(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft_id = _import()["draft_id"]
    monkeypatch.setattr(config, "workspace_context", lambda: (root, 1))

    with pytest.raises(tools.ToolError, match="another workspace"):
        _plan(draft_id)
    with pytest.raises(tools.ToolError, match="another workspace"):
        tools.dispatch("case_draft_review", {"draft_id": draft_id})
    with pytest.raises(tools.ToolError, match="another workspace"):
        tools.dispatch("case_draft_edit", {
            "draft_id": draft_id, "revision": 1, "ops": [{"op": "set_end_time", "end_time_s": 5}]})


def test_an_expired_draft_is_refused(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    draft_id = _import()["draft_id"]
    later = _stored(draft_id).expires_at + 1
    monkeypatch.setattr(case_draft_store, "time", types.SimpleNamespace(time=lambda: later))

    with pytest.raises(tools.ToolError, match="expired"):
        _plan(draft_id)


def test_no_tool_result_carries_a_long_pipes_list(root: Path) -> None:
    imported = _import("synthetic_network.csv")
    draft_id = imported["draft_id"]
    results = [
        imported,
        *(tools.dispatch("case_draft_review", {"draft_id": draft_id, "page": page}) for page in (1, 4, 7)),
        tools.dispatch("case_draft_edit", {
            "draft_id": draft_id, "revision": 1, "ops": [{"op": "resegment", "max_section_m": 2.0}]}),
    ]

    for result in results:
        assert all(len(entries) <= 50 for entries in _pipes_lists(result))
        assert _size(result) < _RESULT_LIMIT


def test_the_new_tools_write_only_the_private_draft_store() -> None:
    gated = set(plan_model.OFFERED_KINDS)
    for name in _NEW_TOOLS:
        tool = tools.TOOLS[name]
        assert tool.side_effect is False
        assert name not in gated
        assert "approval_token" not in tool.parameters["properties"]
        assert "allOf" not in tool.parameters and "if" not in tool.parameters
    guidance = tools.TOOLS["pipe_table_import"].description
    assert "draft_id" in guidance and "never rebuild" in guidance.lower()
    assert "draft_id" in tools.TOOLS["case_edit_plan"].parameters["properties"]


def test_the_schema_budget_holds_for_the_whole_catalog_and_each_new_tool() -> None:
    specs = tools.tool_specs()
    by_name = {spec["name"]: spec for spec in specs}

    assert len(json.dumps(specs)) <= _CATALOG_LIMIT
    assert len(json.dumps(OpenAIChatApiClient._convert_tools(specs))) <= _CATALOG_LIMIT
    for name in _NEW_TOOLS:
        assert len(json.dumps(by_name[name])) <= _TOOL_LIMIT, name
    assert "CaseSpec" not in json.dumps(by_name["case_draft_edit"])


def test_a_stated_start_state_reaches_the_draft_and_survives_an_edit(root: Path) -> None:
    automatic = _import()
    assert automatic["initial_state"]["stated"] is False
    # The shipped template is now a 1.2x drop (2.4 bar source, 2.0 bar sinks),
    # below the 1.5x warning ratio, so the automatic start is not flagged.
    assert automatic["start_warning"] is None

    result = _import(initial_conditions={"pressure_pa": 300000, "temperature_c": 30})
    assert result["initial_state"] == {"pressure_pa": 300000.0, "temperature_c": 30.0, "stated": True}
    assert result["start_warning"] is None

    tools.dispatch("case_draft_edit", {
        "draft_id": result["draft_id"], "revision": 1, "ops": [{"op": "set_end_time", "end_time_s": 60}],
    })
    initial = _stored(result["draft_id"]).spec["initial_conditions"]
    assert (initial["pressure_pa"], initial["temperature_c"]) == (300000.0, 30.0)


_AMBIENT_THERMAL = {
    "model": "ambient_h_given",
    "ambient_temperature_c": 20.0,
    "outer_heat_transfer_coefficient_w_m2k": 10.0,
    "wall": {
        "thickness_m": 0.01,
        "material": {
            "conductivity_w_mk": 50.0,
            "heat_capacity_j_kgk": 500.0,
            "density_kg_m3": 7850.0,
        },
    },
}


def test_set_fluid_edit_changes_the_reference_and_label(root: Path) -> None:
    draft_id = _import()["draft_id"]

    edited = tools.dispatch(
        "case_draft_edit",
        {"draft_id": draft_id, "revision": 1, "ops": [
            {"op": "set_fluid", "pvt_reference": "other.tab", "fluid_label": "FLUID-B"}]},
    )
    spec = _stored(draft_id).spec

    assert edited["revision"] == 2
    assert spec["pvt_reference"] == "other.tab" and spec["fluid_label"] == "FLUID-B"


def test_set_fluid_accepts_a_partial_update(root: Path) -> None:
    draft_id = _import()["draft_id"]

    tools.dispatch(
        "case_draft_edit",
        {"draft_id": draft_id, "revision": 1, "ops": [{"op": "set_fluid", "fluid_label": "FLUID-C"}]},
    )
    spec = _stored(draft_id).spec

    assert spec["fluid_label"] == "FLUID-C" and spec["pvt_reference"] == "fluid.tab"


def test_set_thermal_edit_changes_the_thermal_model(root: Path) -> None:
    draft_id = _import()["draft_id"]

    edited = tools.dispatch(
        "case_draft_edit",
        {"draft_id": draft_id, "revision": 1, "ops": [{"op": "set_thermal", "thermal": _AMBIENT_THERMAL}]},
    )
    spec = _stored(draft_id).spec

    assert edited["revision"] == 2
    assert spec["thermal"]["model"] == "ambient_h_given"


def test_resegment_accepts_max_ratio_and_import_takes_it(root: Path) -> None:
    loose = _import("synthetic_network.csv", segmentation={"max_section_m": 1.0, "max_ratio": 4.0})
    assert loose["created"] is True
    assert loose["junction_warning_count"] < _import("synthetic_network.csv")["junction_warning_count"]

    before = _import("synthetic_network.csv")
    after = tools.dispatch(
        "case_draft_edit",
        {"draft_id": before["draft_id"], "revision": 1, "ops": [{"op": "resegment", "max_ratio": 4.0}]},
    )

    assert after["revision"] == 2
    assert after["junction_warning_count"] < before["junction_warning_count"]
    assert after["counts"]["sections"] == before["counts"]["sections"]
    assert _stored(before["draft_id"]).revision == 2


def test_resegment_rejects_a_max_ratio_outside_its_bounds(root: Path) -> None:
    draft_id = _import()["draft_id"]

    with pytest.raises(tools.ToolError):
        tools.dispatch(
            "case_draft_edit",
            {"draft_id": draft_id, "revision": 1, "ops": [{"op": "resegment", "max_ratio": 10.0}]},
        )

    assert _stored(draft_id).revision == 1


def test_set_fluid_rebuild_failure_keeps_the_draft(root: Path) -> None:
    draft_id = _import()["draft_id"]

    with pytest.raises(tools.ToolError):
        tools.dispatch(
            "case_draft_edit",
            {"draft_id": draft_id, "revision": 1, "ops": [{"op": "set_fluid", "pvt_reference": "../x.tab"}]},
        )

    assert _stored(draft_id).revision == 1
    assert _stored(draft_id).spec["pvt_reference"] == "fluid.tab"


def test_set_fluid_and_set_thermal_reject_bad_input_and_keep_the_draft(root: Path) -> None:
    draft_id = _import()["draft_id"]

    with pytest.raises(tools.ToolError):
        tools.dispatch(
            "case_draft_edit",
            {"draft_id": draft_id, "revision": 1, "ops": [{"op": "set_fluid"}]},
        )
    with pytest.raises(tools.ToolError):
        tools.dispatch(
            "case_draft_edit",
            {"draft_id": draft_id, "revision": 1, "ops": [
                {"op": "set_thermal", "thermal": {"model": "not_a_model"}}]},
        )

    assert _stored(draft_id).revision == 1


def test_a_stated_max_time_step_reaches_the_draft(root: Path) -> None:
    result = _import(max_dt_s=1)

    assert result["created"] is True
    assert _stored(result["draft_id"]).spec["integration"]["max_dt_s"] == 1.0
    tools.dispatch("case_draft_edit", {
        "draft_id": result["draft_id"], "revision": 1, "ops": [{"op": "set_end_time", "end_time_s": 60}],
    })
    assert _stored(result["draft_id"]).spec["integration"]["max_dt_s"] == 1.0
