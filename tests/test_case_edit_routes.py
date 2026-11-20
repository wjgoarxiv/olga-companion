"""A user edits a .genkey by hand through the same reviewed transaction an assistant edit uses.

Owner decision 2026-11-17 (option A, value table): rows come from the case, the plan is the
assistant's own case_edit_plan transaction, the approval is minted by the user's click for that
exact reviewed edit, and the result is a new file; the source is never changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import case_edit_table, workspace
from olga_companion.agent import session_token
from olga_companion.examples import install_example
from olga_companion.sidecar import app

client = TestClient(app)
SPECS = Path(__file__).resolve().parents[1] / "resources" / "examples" / "specs"


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    private = tmp_path / "private"
    root.mkdir()
    private.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(private / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    return root


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install(ws: Path, example_id: str) -> Path:
    return ws / install_example(example_id)["case_rel"]


def _rows(case: Path) -> dict:
    response = client.get("/api/case-edit/rows", params={"rel": case.name})
    assert response.status_code == 200, response.text
    return response.json()


def _row(rows: dict, row_id: str) -> dict:
    return next(row for row in rows["rows"] if row["id"] == row_id)


def _plan(rows: dict, operations: list[dict], **override) -> object:
    body = {
        "source": rows["source"],
        "source_hash": rows["source_hash"],
        "context_generation": rows["context_generation"],
        "operations": operations,
        **override,
    }
    return client.post("/api/case-edit/plan", json=body, headers=_headers())


def _publish(plan: dict, **override) -> object:
    body = {
        "transaction_id": plan["transaction_id"],
        "source_hash": plan["source_hash"],
        "compiled_hash": plan["compiled_hash"],
        "destination_rel": plan["destination_rel"],
        "context_generation": plan["context_generation"],
        "approved": True,
        **override,
    }
    return client.post("/api/case-edit/publish", json=body, headers=_headers())


OUTLET_5_BAR = {"op": "set_boundary_pressure", "node": "OUTLET", "pressure_pa": 500000.0}


def test_rows_are_the_values_of_the_case_spec(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    spec = json.loads((SPECS / "valve_shut_in.json").read_text(encoding="utf-8"))
    rows = _rows(case)
    assert rows["marked"] is True
    assert rows["source_hash"] == _sha(case)
    assert _row(rows, "integration.end_time_s")["value"] == spec["integration"]["end_time_s"]
    assert _row(rows, "nodes.OUTLET.pressure_pa")["value"] == spec["nodes"][1]["pressure_pa"]
    assert _row(rows, "nodes.INLET.temperature_c")["value"] == spec["nodes"][0]["temperature_c"]
    assert _row(rows, "massflow_sources.FEED.mass_flow_kg_s")["value"] == spec["massflow_sources"][0]["mass_flow_kg_s"]
    valve = _row(rows, "equipment.ESD.opening")
    assert valve["value"] == spec["equipment"][0]["opening"]
    assert valve["note"] == "schedule"
    assert _row(rows, "flowpaths.MAIN.pipes.UPSTREAM.roughness_m")["op"] == {
        "op": "set_pipe_roughness", "flowpath": "MAIN", "pipe": "UPSTREAM",
    }


def test_a_case_without_the_marker_offers_only_endtime(ws: Path) -> None:
    case = ws / "hand.genkey"
    case.write_text(
        'CASE LABEL=hand\nINTEGRATION ENDTIME=7200 s, DTSTART=0.01 s\nENDCASE\n', encoding="utf-8"
    )
    rows = case_edit_table.editable_rows(case)
    assert rows["marked"] is False
    assert [(row["id"], row["value"]) for row in rows["rows"]] == [("integration.end_time_s", 7200.0)]


def test_rows_refuse_a_path_outside_the_workspace(ws: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.genkey"
    outside.write_text("CASE\n", encoding="utf-8")
    response = client.get("/api/case-edit/rows", params={"rel": str(outside)})
    assert response.status_code == 400


def test_plan_reviews_the_edit_and_writes_nothing(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    before = case.read_bytes()
    rows = _rows(case)
    response = _plan(rows, [OUTLET_5_BAR])
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["publishable"] is True
    assert plan["validation"]["clean"] is True
    assert plan["semantic_diff"][0]["path"] == "nodes.OUTLET.pressure_pa"
    assert plan["destination_rel"] == case.with_name(f"{case.stem}.edit1.genkey").name
    assert case.read_bytes() == before
    assert not (ws / plan["destination_rel"]).exists()


def test_plan_needs_the_session_token(ws: Path) -> None:
    rows = _rows(_install(ws, "valve-shut-in"))
    body = {"source": rows["source"], "source_hash": rows["source_hash"],
            "context_generation": rows["context_generation"], "operations": [OUTLET_5_BAR]}
    assert client.post("/api/case-edit/plan", json=body).status_code in (401, 403)


def test_plan_on_a_changed_file_is_a_conflict(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    rows = _rows(case)
    case.write_bytes(case.read_bytes() + b"\n")
    response = _plan(rows, [OUTLET_5_BAR])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_source"


def test_plan_on_another_workspace_generation_is_a_conflict(ws: Path) -> None:
    rows = _rows(_install(ws, "valve-shut-in"))
    response = _plan(rows, [OUTLET_5_BAR], context_generation=rows["context_generation"] + 1)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_context"


@pytest.mark.parametrize("operation", [
    {"op": "set_boundary_pressure", "node": "OUTLET", "pressure_pa": -1.0},
    {"op": "set_integration", "end_time_s": 0.0},
    {"op": "delete_everything"},
])
def test_a_bad_edit_is_refused_with_a_reason_and_nothing_is_stored(ws: Path, operation: dict) -> None:
    case = _install(ws, "valve-shut-in")
    response = _plan(_rows(case), [operation])
    if response.status_code == 200:
        plan = response.json()
        assert plan["publishable"] is False
        assert plan["errors"], plan
    else:
        assert response.status_code == 400
        assert response.json()["detail"]["message"]
    assert sorted(path.name for path in case.parent.glob("*.genkey")) == [case.name]


def test_publish_writes_the_reviewed_bytes_to_a_new_file_and_keeps_the_source(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    before = case.read_bytes()
    plan = _plan(_rows(case), [OUTLET_5_BAR]).json()
    response = _publish(plan)
    assert response.status_code == 200, response.text
    published = ws / plan["destination_rel"]
    assert _sha(published) == plan["compiled_hash"]
    assert case.read_bytes() == before
    assert workspace.active()["name"] == published.name
    again = _rows(published)
    assert _row(again, "nodes.OUTLET.pressure_pa")["value"] == 500000.0


def test_publish_needs_the_approval_click_and_the_token(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    plan = _plan(_rows(case), [OUTLET_5_BAR]).json()
    assert _publish(plan, approved=False).status_code == 400
    body = {key: plan[key] for key in ("transaction_id", "source_hash", "compiled_hash", "destination_rel", "context_generation")}
    assert client.post("/api/case-edit/publish", json={**body, "approved": True}).status_code in (401, 403)
    assert not (ws / plan["destination_rel"]).exists()


def test_publish_refuses_a_hash_that_was_not_reviewed(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    plan = _plan(_rows(case), [OUTLET_5_BAR]).json()
    response = _publish(plan, compiled_hash="0" * 64)
    assert response.status_code in (400, 409)
    assert not (ws / plan["destination_rel"]).exists()


def test_a_source_changed_after_review_is_not_published(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    plan = _plan(_rows(case), [OUTLET_5_BAR]).json()
    case.write_bytes(case.read_bytes() + b"\n")
    response = _publish(plan)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_source"
    assert not (ws / plan["destination_rel"]).exists()


def test_a_second_publish_of_the_same_edit_writes_nothing_new(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    plan = _plan(_rows(case), [OUTLET_5_BAR]).json()
    assert _publish(plan).status_code == 200
    published = ws / plan["destination_rel"]
    first = published.read_bytes()
    second = _publish(plan)
    assert second.status_code == 200
    assert second.json()["published_hash"] == plan["compiled_hash"]
    from olga_companion import workspace as _workspace
    _workspace.set_active_path(str(case))
    third = _publish(plan)
    assert third.status_code == 200
    assert Path(_workspace.active_path()).resolve() == published.resolve()
    assert published.read_bytes() == first
    assert sorted(path.name for path in case.parent.glob("*.genkey")) == sorted([case.name, published.name])


def test_edited_names_count_up_and_never_reuse_a_file(tmp_path: Path) -> None:
    case = tmp_path / "line.genkey"
    case.write_text("x", encoding="utf-8")
    assert case_edit_table.edited_name(case) == "line.edit1.genkey"
    (tmp_path / "line.edit1.genkey").write_text("x", encoding="utf-8")
    assert case_edit_table.edited_name(case) == "line.edit2.genkey"
    assert case_edit_table.edited_name(tmp_path / "line.edit1.genkey") == "line.edit2.genkey"


def test_a_case_the_app_did_not_compile_edits_its_end_time_end_to_end(ws: Path) -> None:
    case = _install(ws, "simple-pipeline")
    rows = _rows(case)
    assert rows["marked"] is False
    assert [row["id"] for row in rows["rows"]] == ["integration.end_time_s"]
    plan = _plan(rows, [{"op": "set_integration", "end_time_s": 7200.0}]).json()
    assert plan["publishable"] is True, plan
    response = _publish(plan)
    assert response.status_code == 200, response.text
    assert _row(_rows(ws / plan["destination_rel"]), "integration.end_time_s")["value"] == 7200.0


def test_an_app_case_changed_by_hand_offers_no_rows(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    case.write_bytes(case.read_bytes() + b"! a note added by hand\n")
    rows = _rows(case)
    assert rows["rows"] == []
    assert rows["reason"] == "not_exact_compile"


def test_an_infinite_end_time_offers_no_row(tmp_path: Path) -> None:
    case = tmp_path / "hand.genkey"
    case.write_text("CASE LABEL=hand\nINTEGRATION ENDTIME=1e999 s\nENDCASE\n", encoding="utf-8")
    assert case_edit_table.editable_rows(case)["rows"] == []


def test_publish_refuses_a_name_the_table_did_not_plan(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    plan = _plan(_rows(case), [OUTLET_5_BAR]).json()
    response = _publish(plan, destination_rel="elsewhere.genkey")
    assert response.status_code == 400
    assert not (ws / "elsewhere.genkey").exists()


def test_publish_refuses_a_transaction_without_a_source(ws: Path) -> None:
    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    install_example("valve-shut-in")
    spec = json.loads((SPECS / "valve_shut_in.json").read_text(encoding="utf-8"))
    spec["pvt_reference"] = next(ws.rglob("*.tab")).relative_to(ws).as_posix()
    planned = plan_case_edits(spec, [OUTLET_5_BAR], expected_hash=case_spec_hash(spec), workspace_root=ws, context_generation=0)
    assert planned.publishable is True, getattr(planned, "errors", planned)
    response = _publish({
        "transaction_id": planned.transaction_id, "source_hash": planned.source_hash,
        "compiled_hash": planned.compiled_hash, "destination_rel": "draft.edit1.genkey", "context_generation": 0,
    })
    assert response.status_code == 400
    assert not (ws / "draft.edit1.genkey").exists()


def test_an_uncertain_save_is_a_readable_answer_not_a_crash(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion import case_publish
    from olga_companion.case_publish_types import PublishOutcomeUncertainError

    case = _install(ws, "valve-shut-in")
    plan = _plan(_rows(case), [OUTLET_5_BAR]).json()

    def uncertain(*_args, **_kwargs):
        raise PublishOutcomeUncertainError(plan["transaction_id"])

    monkeypatch.setattr(case_publish, "publish_case", uncertain)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/case-edit/publish",
        json={key: plan[key] for key in ("transaction_id", "source_hash", "compiled_hash", "destination_rel", "context_generation")} | {"approved": True},
        headers=_headers(),
    )
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "uncertain"


def test_pipe_diameter_is_a_row_and_publishes_to_a_new_copy(ws: Path) -> None:
    # 0.1.20 row 3: the edit table changes a pipe's diameter through the same reviewed path.
    case = _install(ws, "valve-shut-in")
    spec = json.loads((SPECS / "valve_shut_in.json").read_text(encoding="utf-8"))
    rows = _rows(case)
    row = _row(rows, "flowpaths.MAIN.pipes.UPSTREAM.diameter_m")
    upstream = next(pipe for pipe in spec["flowpaths"][0]["pipes"] if pipe["label"] == "UPSTREAM")
    assert row["value"] == upstream["diameter_m"]
    assert row["op"] == {"op": "set_pipe_geometry", "flowpath": "MAIN", "pipe": "UPSTREAM"}
    before = case.read_bytes()
    plan = _plan(rows, [{**row["op"], "diameter_m": 0.25}]).json()
    assert plan["publishable"] is True, plan
    assert plan["semantic_diff"][0]["path"] == "flowpaths.MAIN.pipes.UPSTREAM.geometry"
    published = _publish(plan)
    assert published.status_code == 200, published.text
    copy = ws / plan["destination_rel"]
    assert "DIAMETER=0.25" in copy.read_text(encoding="utf-8").replace(" ", "")
    assert case.read_bytes() == before


def test_a_zero_diameter_is_refused_before_anything_is_stored(ws: Path) -> None:
    rows = _rows(_install(ws, "valve-shut-in"))
    op = _row(rows, "flowpaths.MAIN.pipes.UPSTREAM.diameter_m")["op"]
    response = _plan(rows, [{**op, "diameter_m": 0.0}])
    assert response.status_code in (200, 400, 422)
    if response.status_code == 200:
        assert response.json()["publishable"] is False


def test_coverage_counts_pipe_diameter_as_a_table_key(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    rows = case_edit_table.editable_rows(case)["rows"]
    from olga_companion.case_lint import keyword_coverage
    assert "PIPE.DIAMETER" in keyword_coverage(case, rows)["table"]


TIMING = ("max_dt_s", "min_dt_s", "dt_start_s", "trend_interval_s", "profile_interval_s", "output_interval_s")


def test_time_step_and_output_intervals_are_rows(ws: Path) -> None:
    # 0.1.20 row 4: six timing values, each marked stated or derived.
    rows = _rows(_install(ws, "valve-shut-in"))
    for field in TIMING:
        row = _row(rows, f"integration.{field}")
        assert row["op"] == {"op": "set_time_step"}
        assert row.get("note") in (None, "derived", "default", "unset")
        if row.get("note") is not None and field in ("min_dt_s", "dt_start_s"):
            assert row["note"] == "default", "MINDT and DTSTART do not follow the end time"
    end = _row(rows, "integration.end_time_s")["value"]
    trend = _row(rows, "integration.trend_interval_s")
    if trend.get("note") == "derived":
        assert trend["value"] == end / 60


def test_a_time_step_edit_publishes_and_states_the_value(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    rows = _rows(case)
    end = _row(rows, "integration.end_time_s")["value"]
    plan = _plan(rows, [{"op": "set_time_step", "max_dt_s": end / 20}]).json()
    assert plan["publishable"] is True, plan
    assert plan["semantic_diff"][0]["path"] == "integration.max_dt_s"
    assert _publish(plan).status_code == 200
    text = (ws / plan["destination_rel"]).read_text(encoding="utf-8").replace(" ", "")
    assert f"MAXDT={end / 20:g}s" in text


@pytest.mark.parametrize("operation", [
    {"op": "set_time_step", "min_dt_s": 5.0, "max_dt_s": 1.0},
    {"op": "set_time_step", "trend_interval_s": 1e-6, "min_dt_s": 1e-3},
    {"op": "set_time_step", "max_dt_s": 1e9},
    {"op": "set_time_step"},
])
def test_timing_rules_refuse_a_bad_edit(ws: Path, operation: dict) -> None:
    rows = _rows(_install(ws, "valve-shut-in"))
    response = _plan(rows, [operation])
    assert response.status_code in (200, 400, 422)
    if response.status_code == 200:
        assert response.json()["publishable"] is False


def test_a_hand_made_case_still_offers_only_endtime(ws: Path) -> None:
    case = ws / "hand.genkey"
    case.write_text('CASE LABEL=hand\nINTEGRATION ENDTIME=7200 s, MAXDT=10 s\nENDCASE\n', encoding="utf-8")
    rows = case_edit_table.editable_rows(case)["rows"]
    assert [row["id"] for row in rows] == ["integration.end_time_s"]


def test_coverage_names_each_timing_key(ws: Path) -> None:
    case = _install(ws, "valve-shut-in")
    rows = case_edit_table.editable_rows(case)["rows"]
    from olga_companion.case_lint import keyword_coverage
    table = keyword_coverage(case, rows)["table"]
    for key in ("INTEGRATION.MAXDT", "INTEGRATION.MINDT", "INTEGRATION.DTSTART", "TREND.DTPLOT", "PROFILE.DTPLOT", "OUTPUT.DTOUT"):
        assert key in table, key


THERMAL_FIELDS = {
    "ambient_temperature_c": 5.0, "outer_heat_transfer_coefficient_w_m2k": 10.0, "wall_thickness_m": 0.0127,
    "wall_conductivity_w_mk": 45.0, "wall_heat_capacity_j_kgk": 470.0, "wall_density_kg_m3": 7850.0,
}


def test_an_ambient_case_offers_its_heat_transfer_values(ws: Path) -> None:
    # 0.1.20 row 5: the cooling-line example has an ambient thermal model.
    rows = _rows(_install(ws, "cooling-line"))
    for field, value in THERMAL_FIELDS.items():
        row = _row(rows, f"thermal.{field}")
        assert row["value"] == value
        assert row["op"] == {"op": "set_thermal_value"}


def test_an_adiabatic_case_offers_no_heat_transfer_rows(ws: Path) -> None:
    rows = _rows(_install(ws, "valve-shut-in"))
    assert not [row for row in rows["rows"] if row["id"].startswith("thermal.")]


def test_a_wall_thickness_edit_is_reviewed_with_the_value_on_the_card_and_published(ws: Path) -> None:
    case = _install(ws, "cooling-line")
    rows = _rows(case)
    plan = _plan(rows, [{"op": "set_thermal_value", "wall_thickness_m": 0.02}]).json()
    assert plan["publishable"] is True, plan
    assert plan["semantic_diff"][0]["path"] == "thermal.wall_thickness_m"
    assert _publish(plan).status_code == 200
    copy = ws / plan["destination_rel"]
    assert "THICKNESS=0.02" in copy.read_text(encoding="utf-8").replace(" ", "").replace("(", "")


@pytest.mark.parametrize("operation", [
    {"op": "set_thermal_value", "outer_heat_transfer_coefficient_w_m2k": 0.0},
    {"op": "set_thermal_value", "wall_thickness_m": 2.0},
    {"op": "set_thermal_value"},
])
def test_a_bad_heat_transfer_value_is_refused(ws: Path, operation: dict) -> None:
    rows = _rows(_install(ws, "cooling-line"))
    response = _plan(rows, [operation])
    assert response.status_code in (200, 400, 422)
    if response.status_code == 200:
        assert response.json()["publishable"] is False


def test_a_heat_transfer_value_on_an_adiabatic_case_is_refused(ws: Path) -> None:
    rows = _rows(_install(ws, "valve-shut-in"))
    response = _plan(rows, [{"op": "set_thermal_value", "ambient_temperature_c": 4.0}])
    assert response.status_code in (200, 400, 422)
    if response.status_code == 200:
        assert response.json()["publishable"] is False


def test_coverage_names_the_heat_transfer_keys(ws: Path) -> None:
    case = _install(ws, "cooling-line")
    rows = case_edit_table.editable_rows(case)["rows"]
    from olga_companion.case_lint import keyword_coverage
    table = keyword_coverage(case, rows)["table"]
    for key in ("HEATTRANSFER.TAMBIENT", "HEATTRANSFER.HAMBIENT", "WALL.THICKNESS", "MATERIAL.CONDUCTIVITY", "MATERIAL.CAPACITY", "MATERIAL.DENSITY"):
        assert key in table, key


def _stopped_run(monkeypatch: pytest.MonkeyPatch, case: Path, sha: str, stop_reason: dict | None) -> None:
    from olga_companion import sidecar, sidecar_case_edit_routes

    monkeypatch.setattr(sidecar, "run_status", lambda run_id: {"run_id": run_id, "state": "failed", "stop_reason": stop_reason})
    monkeypatch.setattr(sidecar_case_edit_routes, "_run_source", lambda run_id: {"resolved_path": str(case), "sha256": sha})


MAXDT_REJECTED = {"code": "input_rejected", "pointer": {"kind": "keyword", "component": "INTEGRATION", "keyword": "INTEGRATION", "key": "MAXDT"}}


def test_a_stopped_run_points_at_the_row_of_its_own_case(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _install(ws, "valve-shut-in")
    _stopped_run(monkeypatch, case, _sha(case), MAXDT_REJECTED)
    response = client.get("/api/case-edit/remedy", params={"run_id": "abc123def456"})
    assert response.status_code == 200, response.text
    assert response.json() == {"rel": case.name, "row_id": "integration.max_dt_s", "reason_key": "row"}


def test_a_case_changed_since_the_run_is_refused(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _install(ws, "valve-shut-in")
    _stopped_run(monkeypatch, case, "0" * 64, MAXDT_REJECTED)
    body = client.get("/api/case-edit/remedy", params={"run_id": "abc123def456"}).json()
    assert body == {"rel": case.name, "row_id": None, "reason_key": "source_changed"}


def test_a_run_outside_the_workspace_points_nowhere(ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "elsewhere.genkey"
    outside.write_text("CASE\n", encoding="utf-8")
    _stopped_run(monkeypatch, outside, _sha(outside), MAXDT_REJECTED)
    body = client.get("/api/case-edit/remedy", params={"run_id": "abc123def456"}).json()
    assert body == {"rel": None, "row_id": None, "reason_key": "outside_workspace"}


def test_the_remedy_never_writes(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _install(ws, "valve-shut-in")
    before = sorted(path.name for path in ws.iterdir())
    _stopped_run(monkeypatch, case, _sha(case), MAXDT_REJECTED)
    client.get("/api/case-edit/remedy", params={"run_id": "abc123def456"})
    assert sorted(path.name for path in ws.iterdir()) == before
