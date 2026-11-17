"""T4 (WS4) — the Results view lists .tpl/.ppl files and fetches a variable's
time series (JSON) for the interactive trend chart."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import results as R
from olga_companion.sidecar import app

FIX = Path(__file__).parent / "fixtures" / "results"

pytestmark = pytest.mark.skipif(not (FIX / "fixture.tpl").exists(), reason="result fixtures unavailable")


def test_workspace_results_lists_tpl_ppl(monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    client = TestClient(app)
    r = client.get("/api/workspace/results")
    assert r.status_code == 200
    names = {x["name"] for x in r.json()["results"]}
    assert "fixture.tpl" in names  # .tpl/.ppl are surfaced, unlike the case list


def test_results_series_route_returns_a_trend(monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    R._LOAD_CACHE.clear()
    var = R.load_result(str(FIX / "fixture.tpl"))["variables"][0]["variable"]
    client = TestClient(app)
    s = client.post("/api/results/series", json={"rel": "fixture.tpl", "variable": var})
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["variable"] == var
    assert isinstance(body["time"], list) and len(body["time"]) >= 1
    assert isinstance(body["values"], list)


def test_results_series_refuses_traversal(monkeypatch):
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(FIX))
    client = TestClient(app)
    s = client.post("/api/results/series", json={"rel": "../../../etc/passwd", "variable": "HOL"})
    assert s.status_code >= 400
