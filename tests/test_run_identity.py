"""0.1.22 row 3: a run of an approved edit copy is named by the change that was approved.

The change list is kept with the reviewed transaction and found again only through a completed publish
receipt whose published hash equals the hash of the case the run used. Nothing is guessed from names.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_case_edit_routes import _plan, _publish, _rows, ws  # noqa: F401
from test_controller_edit_table import _loop_case

from olga_companion import case_transaction_store, run_identity
from olga_companion.result_inventory import scan_run_results
from olga_companion.run_records import write_run_record

SETPOINT = {"op": "set_controller_value", "label": "PC", "setpoint": 2_500_000.0}


def _published(ws: Path) -> tuple[dict, str]:  # noqa: F811
    plan = _plan(_rows(_loop_case(ws)), [SETPOINT]).json()
    assert plan["publishable"] is True, plan
    assert _publish(plan).status_code == 200
    copy = ws / plan["destination_rel"]
    return plan, hashlib.sha256(copy.read_bytes()).hexdigest()


def _run(runs: Path, run_id: str, source_name: str, sha: str) -> None:
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "case.tpl").write_text("OLGA trend file header line\n", encoding="utf-8")
    write_run_record(run_dir, {
        "schema_version": 1, "run_id": run_id, "phase": "terminal", "state": "completed",
        "source": {"name": source_name, "sha256": sha, "staged_sha256": sha},
        "companions": [], "runtime": {"candidate_id": "c", "runtime_id": "r", "version": "2022.1.0", "kind": "engine", "exe": "x"},
        "selection_id": "s", "validation": {}, "timestamps": {"prepared_at": None, "started_at": None, "finished_at": None},
        "command": [], "exit_code": 0, "failure": None, "outputs": [{"name": "case.tpl", "sha256": None}],
    })


def test_a_published_copy_is_found_by_its_hash_with_the_approved_change(ws: Path) -> None:  # noqa: F811
    plan, sha = _published(ws)
    found = run_identity.approved_changes_by_hash()[sha]
    assert found["source_name"] == "loop_case.genkey"
    assert found["changes"] == [{"path": "controllers.PC.setpoint", "before": 2_000_000.0, "after": 2_500_000.0, "unit": "Pa"}]


def test_review_r5_a_grouped_loop_change_carries_the_setpoint_unit(ws: Path) -> None:  # noqa: F811
    grouped = {"op": "set_controller_value", "label": "PC", "setpoint": 2_500_000.0, "gain": 0.8}
    plan = _plan(_rows(_loop_case(ws)), [grouped]).json()
    assert plan["publishable"] is True, plan
    assert _publish(plan).status_code == 200
    sha = hashlib.sha256((ws / plan["destination_rel"]).read_bytes()).hexdigest()
    changes = run_identity.approved_changes_by_hash()[sha]["changes"]
    assert [change.get("unit") for change in changes if change["path"].startswith("controllers.PC")] == ["Pa"]


def test_a_hand_made_or_unpublished_case_has_no_change(ws: Path) -> None:  # noqa: F811
    plan = _plan(_rows(_loop_case(ws)), [SETPOINT]).json()
    assert plan["publishable"] is True
    index = run_identity.approved_changes_by_hash()
    assert plan["compiled_hash"] not in index, "planned but not approved: no label"
    assert hashlib.sha256(b"hand made").hexdigest() not in index


def test_a_tampered_change_record_is_ignored(ws: Path) -> None:  # noqa: F811
    plan, sha = _published(ws)
    record = case_transaction_store.changes_path(plan["transaction_id"])
    record.write_text(json.dumps({"source_name": 7, "changes": "x"}), encoding="utf-8")
    assert sha not in run_identity.approved_changes_by_hash()


def test_the_results_list_carries_the_change_of_the_case_the_run_used(ws: Path, tmp_path: Path) -> None:  # noqa: F811
    plan, sha = _published(ws)
    runs = tmp_path / "runs"
    _run(runs, "run-a", Path(plan["destination_rel"]).name, sha)
    _run(runs, "run-b", "other.genkey", hashlib.sha256(b"other").hexdigest())
    items = {item["run_id"]: item for item in scan_run_results(runs, list_cap=50, walk_cap=500)}
    assert items["run-a"]["approved_change"]["changes"][0]["path"] == "controllers.PC.setpoint"
    assert "approved_change" not in items["run-b"]
