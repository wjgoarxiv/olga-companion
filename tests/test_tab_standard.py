from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from olga_companion import fluids

FIXTURES = Path(__file__).parent / "fixtures" / "fluids"
STANDARD = FIXTURES / "standard_three.tab"
MISSING_AXES = FIXTURES / "standard_missing_axes.tab"


@pytest.fixture
def toolkit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    scripts = Path(fluids.fluids_toolkit_status()["toolkit_dir"]) / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return tuple(importlib.import_module(name) for name in (
        "tab_parser", "tab_validator", "tab_summarizer",
    ))


def test_standard_missing_axes_are_not_inferred_as_pt(toolkit) -> None:
    parser_module, validator_module, _ = toolkit
    parsed = parser_module.TabParser(MISSING_AXES)
    assert parsed.formulation == ""
    report = validator_module.TabValidator(MISSING_AXES).validate()
    assert any(item["rule_id"] == "V011" for item in report["errors"])


def test_standard_columns_points_and_header_only(toolkit) -> None:
    parser_module, validator_module, _ = toolkit
    full = parser_module.TabParser(STANDARD)
    header = parser_module.TabParser(STANDARD, header_only=True)
    assert full.formulation == "PT"
    assert full.columns == ["PT", "TM", "ROG", "ROHL", "ROWT", "VISWT", "HG", "SEWT"]
    assert full.temperature_grid == [5, 40]
    assert full.pressure_grid == [100000, 10000000]
    assert full.get_property("ROHL") == [2, 1.9, 110, 105]
    assert full.get_property("ROWT") == [999, 992, 1001, 994]
    assert full.get_property("ROL") is None
    assert full.get_property("HG") == [-20000, 20000, -19000, 21000]
    assert header.available_properties == full.available_properties
    assert header.get_property("ROG") is None
    assert full.to_dict()["point_count"] == 4
    assert len(full.point_rows) == 4
    assert header.to_dict()["point_count"] is None
    assert header.to_dict()["point_data_loaded"] is False
    assert header.to_dict()["temperature_range"] == {"min": 5, "max": 40}
    report = validator_module.TabValidator(STANDARD).validate()
    assert report["errors"] == []
    assert report["warnings"] == []


def test_standard_summary_keeps_bubble_metadata_separate(toolkit) -> None:
    _, _, summary_module = toolkit
    summary = summary_module.TabSummarizer(STANDARD)
    data = summary.to_dict()
    assert data["temperature"] == {"min_c": 5, "max_c": 40, "n_points": 2}
    assert data["bubble_temperature"] == {"min_c": -200, "max_c": -140, "n_points": 2}
    assert "Temperature:  5 - 40 C (2 points)" in summary.summarize()
    assert "Bubble T:" in summary.summarize()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("PT, TM", "PT, PT"),
        ("ROG, ROHL", "ROG, ROG"),
        ("ROG, ROHL", "ROG, ROL"),
        ("ROHL, ROWT", "ROHL, UNKNOWN"),
        ("PHASE = THREE", "PHASE = TWO"),
        ("MESHTYPE = STANDARD", "MESHTYPE = UNKNOWN"),
        ("TOTWATERFRACTION = ( .4 )", "TOTWATERFRACTION = ( .4, .5 )"),
        ("TOTWATERFRACTION = ( .4 )", "TOTWATERFRACTION = ( NaN )"),
        ("TOTWATERFRACTION = ( .4 )", "TOTWATERFRACTION = ( 1.1 )"),
        ("TOTWATERFRACTION = ( .4 ),", ""),
        ("TOTWATERFRACTION = ( .4 )", "TOTWATERFRACTION = ( .4 ) UNKNOWN"),
        ("100000, 10000000 ) PA", "100000, 10000000 ) BARG"),
        ("PRESSURE = ( 100000, 10000000 ) PA,", ""),
        ("TEMPERATURE = ( 5, 40 ) C,", ""),
        ("5, 40 ) C", "5, 40 ) F"),
        ("5, 40 ) C", "5, 40 )"),
        ("100000, 10000000 ) PA", "100000, 100000 ) PA"),
        ("100000, 10000000 ) PA", "10000000, 100000 ) PA"),
        ("100000, 10000000 ) PA", "bad, 10000000 ) PA"),
        ("100000, 10000000 ) PA", "Inf, 10000000 ) PA"),
        ("5, 40 ) C", "5, 5 ) C"),
        ("5, 40 ) C", "5, NaN ) C"),
        ("5, 40 ) C", "5 ) C"),
        ("100000, 5, 1, 2", "100001, 5, 1, 2"),
        ("100000, 5, 1, 2", "100000, 6, 1, 2"),
        ("100000, 5, 1, 2", "100000, 5, bad, 2"),
        ("100000, 5, 1, 2", "100000, 5, NaN, 2"),
        ("100000, 5, 1, 2", "100000, 5, Inf, 2"),
        ("100000, 5, 1, 2", "100000, 5, 1e999, 2"),
        ("100000, 5, 1, 2", "100000, 5, , 2"),
        ("100000, 5, 1, 2", "100000, 5, 1, 2, 3"),
        ("100000, 40, .9", "100000, 5, .9"),
        ("-5600 )", "-5600"),
        ("-5600 )", "-5600 ) junk"),
        ("-5600 )", "-5600 )\nPVTTABLE POINT = garbage"),
        ("MOLES = ( .5, .5 )", "MOLES = ( .5, NaN )"),
        ("COLUMNS = (", "PHASE = THREE, COLUMNS = ("),
        ("COLUMNS = ( PT, TM, ROG, ROHL, ROWT, VISWT, HG, SEWT )",
         "COLUMNS = ( PT, TM, ROG, ROHL, ROWT, VISWT, HG, SEWT ) UNKNOWN"),
        ("COLUMNS = (", "PVTFORMULATION = PH, COLUMNS = ("),
    ],
)
def test_standard_rejects_malformed_or_unqualified_input(
    toolkit, tmp_path: Path, old: str, new: str,
) -> None:
    _, validator_module, _ = toolkit
    original = STANDARD.read_text()
    assert old in original
    path = tmp_path / "bad.tab"
    path.write_text(original.replace(old, new, 1))
    report = validator_module.TabValidator(path).validate()
    assert report["errors"], (old, new, report)


@pytest.mark.parametrize("remove_all", [False, True])
def test_standard_rejects_missing_grid_points(toolkit, tmp_path: Path, remove_all: bool) -> None:
    _, validator_module, _ = toolkit
    text = STANDARD.read_text()
    if remove_all:
        text = text[:text.index("PVTTABLE POINT")]
    else:
        text = text[:text.rindex("PVTTABLE POINT")]
    path = tmp_path / "missing.tab"
    path.write_text(text)
    assert validator_module.TabValidator(path).validate()["errors"]


def test_standard_header_inspection_is_not_full_validation(toolkit, tmp_path: Path) -> None:
    parser_module, validator_module, _ = toolkit
    path = tmp_path / "truncated.tab"
    path.write_text(STANDARD.read_text().replace("-5600 )", "-5600"))
    header = parser_module.TabParser(path, header_only=True)
    assert header.to_dict()["point_data_loaded"] is False
    assert header.get_property("ROG") is None
    assert validator_module.TabValidator(path).validate()["errors"]


def test_standard_uses_declared_coordinate_order(toolkit, tmp_path: Path) -> None:
    parser_module, validator_module, _ = toolkit
    text = STANDARD.read_text().replace("PT, TM", "TM, PT")
    for pressure in (100000, 10000000):
        for temperature in (5, 40):
            text = text.replace(f"( {pressure}, {temperature},", f"( {temperature}, {pressure},")
    path = tmp_path / "reordered.tab"
    path.write_text(text)
    parsed = parser_module.TabParser(path)
    assert parsed.get_property("ROWT") == [999, 992, 1001, 994]
    assert validator_module.TabValidator(path).validate()["errors"] == []


def test_standard_cross_check_and_live_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion import genkey_static, workspace
    from olga_companion.agent.simulation_setup_adapter import _LivePreflight
    from olga_companion.simulation_setup_models import (
        ActiveCaseBinding, IntegrationSettings, OutputTarget, RuntimeSelection, SimulationSetup,
    )

    case = tmp_path / "case.genkey"
    table = tmp_path / "fluid.tab"
    shutil.copyfile(FIXTURES / "case_ok.genkey", case)
    shutil.copyfile(STANDARD, table)
    before = case.read_bytes(), table.read_bytes()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(workspace, "active_path", lambda: str(case))
    inspected = fluids.inspect_tab(str(table))
    assert inspected["valid"] is True
    assert inspected["parsed"]["temperature_range"] == {"min": 5, "max": 40}
    assert inspected["source_mutated"] is False
    checked = fluids.consistency(str(case))
    cross_check = checked["references"][0]["cross_check"]
    assert cross_check["valid"] is True
    assert cross_check["warnings"] == []
    setup = SimulationSetup(
        binding=ActiveCaseBinding(kind="active_case", source_sha256=genkey_static.file_sha256(case)),
        integration=IntegrationSettings(end_time_s=3600), outputs=("PT",),
        runtime=RuntimeSelection(candidate_id="candidate-test", runtime_id="runtime-test"), timeout_s=3600,
        output_target=OutputTarget(relative_dir="results/test"), context_generation=7,
    )
    live = _LivePreflight(setup)
    assert live.check_fluids(setup).consistent is True
    assert (case.read_bytes(), table.read_bytes()) == before
    table.write_text(table.read_text().replace("-5600 )", "-5600"))
    assert live.check_fluids(setup).consistent is False
    assert case.read_bytes() == before[0]


def test_standard_inspection_api_preserves_originals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from olga_companion import runner
    from olga_companion.sidecar import app

    table = tmp_path / "standard.tab"
    shutil.copyfile(STANDARD, table)
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "_RUNS", {})
    with TestClient(app) as client:
        response = client.post("/api/fluids/inspect-tab", json={"path": str(table)})
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is True
    assert "ROWT" in result["parsed"]["available_properties"]
    assert result["source_mutated"] is False
    assert table.read_bytes() == STANDARD.read_bytes()


@pytest.mark.parametrize(
    ("old", "new", "rule"),
    [("20 C", "60 C", "V008"), ("50 bara", "150 bara", "V007"),
     ("20 C", "293.15 K", None), ("20 C", "20 UNKNOWN", "V010"),
     ("50 bara", "5000 kPa", None), ("50 bara", "5 MPa", None),
     ("50 bara", "50 barg", "V010"), ("20 C", "NaN C", "V010")],
)
def test_standard_boundary_units_and_coverage(toolkit, tmp_path: Path, old, new, rule) -> None:
    _, validator_module, _ = toolkit
    text = (FIXTURES / "case_ok.genkey").read_text()
    assert old in text
    case = tmp_path / "case.genkey"
    case.write_text(text.replace(old, new))
    result = validator_module.TabValidator(STANDARD, case).validate()
    ids = {finding["rule_id"] for finding in result["errors"] + result["warnings"]}
    assert (not ids) if rule is None else rule in ids


def test_legacy_ph_contract_is_unchanged(toolkit) -> None:
    parser_module, validator_module, summary_module = toolkit
    path = FIXTURES / "fluid.tab"
    parsed = parser_module.TabParser(path)
    header = parser_module.TabParser(path, header_only=True)
    assert parsed.formulation == "PH"
    assert parsed.n_enthalpies == [3, 3, 3]
    assert len(parsed.get_property("ROL")) == 9
    assert header.available_properties == parsed.available_properties
    assert parsed.temperature_grid == []
    assert validator_module.TabValidator(path).validate()["errors"] == []
    assert summary_module.TabSummarizer(path).to_dict()["bubble_temperature"]["min_c"] == -56.558


@pytest.mark.parametrize("ending", ["Inf ) KG/M3", "NaN ) KG/M3", "1020", ", 1020 ) KG/M3"])
def test_legacy_invalid_property_data_stays_invalid(toolkit, tmp_path: Path, ending: str) -> None:
    _, validator_module, _ = toolkit
    text = (FIXTURES / "fluid.tab").read_text().replace("1020.00000 ) KG/M3", ending)
    path = tmp_path / "invalid-ph.tab"
    path.write_text(text)
    assert validator_module.TabValidator(path).validate()["errors"]
