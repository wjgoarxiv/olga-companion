from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import olga_companion.results as results_module
from olga_companion.genkey_static import file_sha256
from olga_companion.results import (
    extract_csv,
    load_result,
    result_capabilities,
    results_toolkit_status,
)
from olga_companion.sidecar import app
from result_test_support import FIXTURES, PPL, TPL
from result_test_support import exports_tmp as exports_tmp

pytestmark = pytest.mark.skipif(
    not results_toolkit_status()["available"], reason="OLGA result toolkit scripts are unavailable"
)


def test_result_toolkit_scripts_available() -> None:
    status = results_toolkit_status()
    assert status["available"] is True
    assert all(status["scripts"].values())


def test_load_tpl_lists_variables() -> None:
    before = file_sha256(TPL)
    result = load_result(str(TPL))
    assert result["ok"] is True
    assert result["file_type"] == "tpl"
    assert len(result["variables"]) == 6
    names = {entry["variable"] for entry in result["variables"]}
    assert {"PT", "TM", "HOL", "LIQC"} <= names
    assert result["time_range"]["start_s"] == 0.0
    assert result["time_range"]["end_s"] == 3600.0
    assert result["source_mutated"] is False
    assert file_sha256(TPL) == before


def test_load_ppl_lists_branches_and_timesteps() -> None:
    result = load_result(str(PPL))
    assert result["ok"] is True
    assert result["file_type"] == "ppl"
    assert result["branches"] == ["PIPELINE"]
    assert result["timesteps"] == [0.0, 1800.0, 3600.0]
    assert result["source_mutated"] is False


def test_malformed_result_file_reports_parser_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    bad = tmp_path / "bad.tpl"
    bad.write_text("this is not a trend file\n", encoding="utf-8")
    result = load_result(str(bad))
    assert result["ok"] is False
    assert result["parser"]["exit_code"] != 0


def test_result_path_trust_boundary(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="workspace or run sandbox"):
        load_result(str(tmp_path / "nope.txt"))
    with pytest.raises(ValueError, match="result file not found"):
        load_result("workspace:missing.tpl")


def test_result_capability_enabled_via_fixture_smoke() -> None:
    caps = result_capabilities()
    assert caps["result_analysis"]["enabled"] is True
    assert caps["result_analysis"]["reason"].strip()


def test_result_capability_fails_closed_without_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(results_module, "SMOKE_FIXTURE", tmp_path / "absent.tpl")
    results_module._fixture_smoke.cache_clear()
    try:
        caps = result_capabilities()
        assert caps["result_analysis"]["enabled"] is False
        assert "missing" in caps["result_analysis"]["reason"].lower()
    finally:
        results_module._fixture_smoke.cache_clear()


def test_results_routes() -> None:
    client = TestClient(app)

    caps = client.get("/api/capabilities")
    assert caps.status_code == 200
    assert caps.json()["result_analysis"]["enabled"] is True

    load = client.post("/api/results/load", json={"path": str(TPL)})
    assert load.status_code == 200
    assert load.json()["ok"] is True

    csv = client.post("/api/results/extract-csv", json={"path": str(TPL), "variables": ["PT"]})
    assert csv.status_code == 200
    assert csv.json()["ok"] is True

    selected = load_result(str(TPL))["variables"][0]
    selected_csv = client.post(
        "/api/results/extract-csv",
        json={"path": str(TPL), "variables": [selected["variable"]], "position": selected["position"]},
    )
    assert selected_csv.status_code == 200, selected_csv.text
    assert selected_csv.json()["row_count"] > 0
    assert selected_csv.json()["provenance"]["position"]
    selected_download = client.get(
        "/api/results/download", params={"path": selected_csv.json()["download_path"]}
    )
    assert selected_download.status_code == 200
    assert selected_csv.json()["download_name"] in selected_download.headers["content-disposition"]

    bad = client.post("/api/results/load", json={"path": str(FIXTURES / "missing.tpl")})
    assert bad.status_code == 400


def test_download_route_is_contained_to_exports() -> None:
    client = TestClient(app)

    outside = client.get("/api/results/download", params={"path": "/etc/passwd"})
    assert outside.status_code == 400

    traversal = client.get("/api/results/download", params={"path": str(FIXTURES / ".." / ".." / "pyproject.toml")})
    assert traversal.status_code == 400

    exported = extract_csv(str(TPL), ["PT"])
    assert exported["ok"] is True
    legit = client.get("/api/results/download", params={"path": exported["csv"]})
    assert legit.status_code == 200
    assert legit.content.startswith(b"\xef\xbb\xbftime_s")
