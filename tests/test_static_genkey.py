from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion.genkey_static import create_preview, modify_copy, require_genkey_path, review_file, toolkit_status
from olga_companion.sidecar import app

SAMPLE_ROOT = Path(__file__).parent / "fixtures" / "cases"
SIMPLE = SAMPLE_ROOT / "simple_pipeline.genkey"
BROKEN = SAMPLE_ROOT / "intentionally_broken.genkey"


pytestmark = pytest.mark.skipif(not SIMPLE.exists(), reason="OLGA skill sample cases are unavailable")


def test_toolkit_scripts_are_available() -> None:
    status = toolkit_status()
    assert status["available"] is True
    assert all(status["scripts"].values())


def test_create_preview_uses_toolkit_builder() -> None:
    result = create_preview("simple_pipeline", endtime_s=7200, pvtfile="./fixture.tab")
    assert result["ok"] is True
    assert result["command"]["script"] == "genkey_builder.py"
    assert "simple_pipeline" in result["command"]["args"]
    assert result["preview"].strip()


def test_review_valid_and_invalid_genkey() -> None:
    valid = review_file(str(SIMPLE))
    assert valid["valid"] is True
    assert valid["validation"]["exit_code"] == 0
    assert "Network Topology" in valid["topology"]["stdout"]

    invalid = review_file(str(BROKEN))
    assert invalid["valid"] is False
    assert invalid["validation"]["exit_code"] != 0
    assert "ERRORS:" in invalid["validation"]["stdout"]


def test_malformed_review_inputs_are_rejected(tmp_path: Path) -> None:
    text_file = tmp_path / "not-a-case.txt"
    text_file.write_text("not genkey", encoding="utf-8")
    with pytest.raises(ValueError, match="Only .genkey"):
        require_genkey_path(str(text_file))

    with pytest.raises(ValueError, match="File not found"):
        require_genkey_path(str(tmp_path / "missing.genkey"))


def test_modify_copy_creates_backup_validates_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "case.genkey"
    shutil.copy2(SIMPLE, source)
    before = source.read_bytes()

    result = modify_copy(str(source), "INTEGRATION", "ENDTIME", "48 h")

    assert result["source_mutated"] is False
    assert source.read_bytes() == before
    assert Path(result["backup"]).exists()
    assert Path(result["modified_copy"]).exists()
    assert result["write"]["exit_code"] == 0
    assert result["validation"]["script"] == "genkey_validator.py"
    assert result["diff"]["script"] == "genkey_diff.py"


def test_sidecar_health_and_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate an OLGA-less host: this dev machine has a real install the T2 glob
    # list now matches, so gate the executable off to assert the disabled reason.
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr("olga_companion.runner.OLGA_EXE_GLOBS", [str(tmp_path / "none" / "OLGA*" / "opi.exe")])
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["app"] == "OLGA Companion"
    assert body["frontend_port"] == 5273
    assert body["sidecar_port"] == 8865
    assert body["capabilities"]["live_olga_run"]["enabled"] is False

    create = client.post("/api/genkey/create", json={"topology": "simple_pipeline", "endtime_s": 3600, "pvtfile": "./fluid.tab"})
    assert create.status_code == 200
    assert create.json()["ok"] is True

    malformed = client.post("/api/genkey/review", json={"path": str(tmp_path / "bad.txt")})
    assert malformed.status_code == 400


def test_sidecar_health_reports_effective_cli_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_FRONTEND_PORT", "5274")
    monkeypatch.setenv("OLGA_SIDECAR_PORT", "8866")

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["frontend_port"] == 5274
    assert response.json()["sidecar_port"] == 8866
