"""The read-only draft network route feeds the topology map before a draft is saved."""

from __future__ import annotations

import json
import shutil
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import case_draft_store, config, sidecar
from olga_companion.agent import approvals, tools

_TESTS = Path(__file__).parent
_TABLES = _TESTS / "fixtures" / "pipe_tables"
_ROUTE_LIMIT = 16 * 1024


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    shutil.copyfile(_TESTS / "fixtures" / "fluids" / "fluid.tab", workspace_root / "fluid.tab")
    for table in _TABLES.glob("*.csv"):
        shutil.copyfile(table, workspace_root / table.name)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(workspace_root))
    monkeypatch.setenv("OLGA_CASE_DRAFT_DIR", str(tmp_path / "drafts"))
    approvals.revoke_all()
    yield workspace_root
    approvals.revoke_all()


def _import(name: str = "small_branch.csv") -> str:
    return tools.dispatch("pipe_table_import", {
        "path": name, "pvt_reference": "fluid.tab", "fluid_label": "FLUID-A",
        "thermal": {"model": "adiabatic"}, "end_time_s": 600,
    })["draft_id"]


def _get(draft_id: str):
    return TestClient(sidecar.app).get(f"/api/case-draft/{draft_id}/topology")


def test_the_route_returns_the_draft_network_as_index_lists(root: Path) -> None:
    draft_id = _import()
    stored = case_draft_store.get_draft(draft_id, context_generation=0)

    response = _get(draft_id)

    assert response.status_code == 200
    body = response.json()
    assert body["draft_id"] == draft_id and body["revision"] == 1
    assert body["counts"] == {
        "nodes": len(stored.spec["nodes"]), "flowpaths": len(stored.spec["flowpaths"]),
        "edges": len(stored.spec["flowpaths"]),
    }
    labels = [label for label, _kind in body["nodes"]]
    assert labels == [node["label"] for node in stored.spec["nodes"]]
    for (source, target, label), flowpath in zip(body["edges"], stored.spec["flowpaths"]):
        assert (labels[source], labels[target], label) == (flowpath["from"], flowpath["to"], flowpath["label"])
    assert {body["kinds"][kind] for _label, kind in body["nodes"]} <= {"junction", "source", "sink"}
    assert "spec" not in body and "pipes" not in response.text


def test_the_synthetic_network_stays_inside_sixteen_kilobytes(root: Path) -> None:
    draft_id = _import("synthetic_network.csv")

    response = _get(draft_id)

    assert response.status_code == 200
    assert response.json()["counts"]["flowpaths"] == 317
    assert len(response.content) < _ROUTE_LIMIT


def test_an_edited_draft_shows_its_new_revision(root: Path) -> None:
    draft_id = _import()
    tools.dispatch("case_draft_edit", {
        "draft_id": draft_id, "revision": 1, "ops": [{"op": "set_end_time", "end_time_s": 900}]})

    assert _get(draft_id).json()["revision"] == 2


def test_an_unknown_or_malformed_draft_is_not_found(root: Path) -> None:
    assert _get("0" * 32).status_code == 404
    assert _get("not-a-draft").status_code == 404


def test_an_expired_draft_is_refused(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    draft_id = _import()
    later = case_draft_store.get_draft(draft_id, context_generation=0).expires_at + 1
    monkeypatch.setattr(case_draft_store, "time", types.SimpleNamespace(time=lambda: later))

    response = _get(draft_id)

    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


def test_a_draft_of_another_workspace_state_is_refused(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    draft_id = _import()
    monkeypatch.setattr(config, "workspace_context", lambda: (root, 1))

    response = _get(draft_id)

    assert response.status_code == 404
    assert "another workspace" in response.json()["detail"]
    assert json.dumps(response.json()).count("SRC_") == 0
