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
