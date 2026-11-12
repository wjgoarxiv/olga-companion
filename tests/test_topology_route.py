"""T3 (WS3) — the Workspace view fetches a case's network graph directly (no chat).

`POST /api/genkey/topology {rel}` resolves the workspace-relative case (containment-
safe) and returns the {nodes, edges, counts} graph the topology canvas renders.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion.sidecar import app
from olga_companion import sidecar

SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases unavailable")


def test_genkey_topology_route_returns_the_network_graph(monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(SAMPLE_ROOT))
    client = TestClient(app)
    r = client.post("/api/genkey/topology", json={"rel": "simple_pipeline.genkey"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["nodes"] == 2
    assert any(e.get("label") == "FLOWPATH_1" for e in body["edges"])


def test_genkey_topology_route_refuses_traversal(monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(SAMPLE_ROOT))
    client = TestClient(app)
    r = client.post("/api/genkey/topology", json={"rel": "../../../etc/passwd"})
    assert r.status_code >= 400  # containment refuses the escape


def test_flowpath_details_route_uses_contained_case_and_rejects_unsafe_label(monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(SAMPLE_ROOT))
    monkeypatch.setattr(
        sidecar,
        "load_flowpath_details",
        lambda path, flowpath: {"flowpath": flowpath, "pipes": [], "summary": {}},
    )
    client = TestClient(app)

    response = client.post(
        "/api/genkey/flowpath-details",
        json={"rel": "simple_pipeline.genkey", "flowpath": "FLOWPATH_1"},
    )

    assert response.status_code == 200
    assert response.json()["flowpath"] == "FLOWPATH_1"
    unsafe = client.post(
        "/api/genkey/flowpath-details",
        json={"rel": "simple_pipeline.genkey", "flowpath": "--output=/tmp/leak"},
    )
    assert unsafe.status_code == 422


def test_flowpath_details_route_uses_workspace_only_resolver(monkeypatch):
    seen = []
    monkeypatch.setattr(sidecar, "_workspace_file", lambda value, suffixes: seen.append((value, suffixes)) or str(SIMPLE))
    monkeypatch.setattr(sidecar, "load_flowpath_details", lambda path, flowpath: {"flowpath": flowpath})
    client = TestClient(app)

    response = client.post(
        "/api/genkey/flowpath-details",
        json={"rel": "simple_pipeline.genkey", "flowpath": "FLOWPATH_1"},
    )

    assert response.status_code == 200
    assert seen == [("simple_pipeline.genkey", {".genkey"})]
