from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import fluids
from olga_companion.genkey_tool_runner import CommandResult
from olga_companion.fluids import (
    consistency,
    fluid_capabilities,
    fluids_toolkit_status,
    inspect_mfl,
    inspect_tab,
    require_fluid_path,
)
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures" / "fluids"
VALID_TAB = FIXTURES / "fluid.tab"
BROKEN_TAB = FIXTURES / "broken.tab"
VALID_MFL = FIXTURES / "fluid.mfl"
GENKEY_OK = FIXTURES / "case_ok.genkey"
GENKEY_MISSING_REF = FIXTURES / "case_missing.genkey"

pytestmark = pytest.mark.skipif(
    not fluids_toolkit_status()["available"], reason="OLGA fluid toolkit scripts are unavailable"
)


def test_fluid_toolkit_scripts_available() -> None:
    status = fluids_toolkit_status()
    assert status["available"] is True
    assert all(status["scripts"].values())


def test_inspect_tab_valid_fixture() -> None:
    before = VALID_TAB.read_bytes()
    result = inspect_tab(str(VALID_TAB))
    assert result["valid"] is True
    assert result["parsed"]["label"] == "FLUID-A"
    assert "ROG" in result["parsed"]["available_properties"]
    assert "ROL" in result["parsed"]["available_properties"]
    assert result["summary_text"].strip()
    assert result["source_mutated"] is False
    assert VALID_TAB.read_bytes() == before


def test_inspect_tab_reports_invalid_content() -> None:
    result = inspect_tab(str(BROKEN_TAB))
    assert result["valid"] is False
    assert result["validation_errors"], "validator evidence must list at least one error"
    assert result["source_mutated"] is False


@pytest.mark.parametrize(
    ("stdout", "exit_code", "timed_out"),
    [
        ("not json", 0, False),
        ("[]", 0, False),
        ("{}", 0, False),
        (json.dumps({"errors": []}), 0, False),
        (json.dumps({"errors": {}, "warnings": []}), 0, False),
        (json.dumps({"errors": [], "warnings": {}}), 0, False),
        (json.dumps({"errors": [], "warnings": []}), 2, False),
        (json.dumps({"errors": [], "warnings": []}), 0, True),
    ],
)
def test_tab_validation_requires_a_completed_tool_and_structured_report(
    monkeypatch: pytest.MonkeyPatch, stdout: str, exit_code: int, timed_out: bool
) -> None:
    command = CommandResult("tab_validator", [], exit_code, stdout, "", timed_out, 1)
    monkeypatch.setattr(fluids, "run_tool", lambda *_args, **_kwargs: command)

    result = fluids._validate_tab(VALID_TAB)

    assert result["valid"] is False
    assert result["errors"], "an unconfirmed check must not look like an error-free table"


def test_tab_validation_keeps_domain_errors_and_nonblocking_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = {"rule_id": "V005", "severity": "WARNING", "message": "grid warning"}
    error = {"rule_id": "V006", "severity": "ERROR", "message": "missing property"}
    for errors, exit_code in [([], 0), ([error], 1)]:
        command = CommandResult(
            "tab_validator", [], exit_code,
            json.dumps({"errors": errors, "warnings": [warning]}), "", False, 1,
        )
        monkeypatch.setattr(fluids, "run_tool", lambda *_args, **_kwargs: command)

        result = fluids._validate_tab(VALID_TAB)

        assert result["valid"] is (not errors)
        assert result["errors"] == errors
        assert result["warnings"] == [warning]


def test_fluid_path_trust_boundary(tmp_path: Path) -> None:
    text_file = tmp_path / "not-a-table.txt"
    text_file.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Only .tab"):
        require_fluid_path(str(text_file), {".tab"})
    with pytest.raises(ValueError, match="File not found"):
        require_fluid_path(str(tmp_path / "missing.tab"), {".tab"})


def test_inspect_mfl_fixture() -> None:
    before = VALID_MFL.read_bytes()
    result = inspect_mfl(str(VALID_MFL))
    assert result["ok"] is True
    assert result["parsed"]["components"] == ["CO2", "N2"]
    assert result["source_mutated"] is False
    assert VALID_MFL.read_bytes() == before


def test_consistency_reports_found_and_missing_references() -> None:
    ok = consistency(str(GENKEY_OK))
    assert ok["total"] == 1
    assert ok["missing"] == 0
    reference = ok["references"][0]
    assert reference["exists"] is True
    assert reference["cross_check"]["valid"] is True
    assert ok["source_mutated"] is False

    missing = consistency(str(GENKEY_MISSING_REF))
    assert missing["total"] == 1
    assert missing["missing"] == 1
    assert missing["references"][0]["exists"] is False
    assert missing["references"][0]["cross_check"] is None


def test_fluid_capability_gates() -> None:
    caps = fluid_capabilities()
    assert caps["fluid_pvt_static"]["enabled"] is True
    assert caps["multiflash"]["enabled"] is False
    assert caps["multiflash"]["reason"].strip()


def test_fluids_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    tab_path = tmp_path / VALID_TAB.name
    mfl_path = tmp_path / VALID_MFL.name
    genkey_path = tmp_path / GENKEY_OK.name
    shutil.copy2(VALID_TAB, tab_path)
    shutil.copy2(VALID_MFL, mfl_path)
    shutil.copy2(GENKEY_OK, genkey_path)
    client = TestClient(app)

    caps = client.get("/api/capabilities")
    assert caps.status_code == 200
    body = caps.json()
    assert body["fluid_pvt_static"]["enabled"] is True
    assert body["multiflash"]["enabled"] is False

    tab = client.post("/api/fluids/inspect-tab", json={"path": str(tab_path)})
    assert tab.status_code == 200
    assert tab.json()["valid"] is True

    mfl = client.post("/api/fluids/inspect-mfl", json={"path": str(mfl_path)})
    assert mfl.status_code == 200
    assert mfl.json()["ok"] is True

    check = client.post("/api/fluids/consistency", json={"path": str(genkey_path)})
    assert check.status_code == 200
    assert check.json()["missing"] == 0

    bad = client.post("/api/fluids/inspect-tab", json={"path": str(tmp_path / "missing.tab")})
    assert bad.status_code == 400
