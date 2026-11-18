"""A .tab from property values the user already has: nothing is calculated, every write is approved.

Offline. The grids below are small synthetic tables, not fluid data.
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import fluid_table, tab_import, workspace
from olga_companion.agent import (
    approval_display,
    approval_execution,
    approvals,
    history,
    pending_approvals,
    plan_model,
    session_token,
    tools,
)
from olga_companion.agent.tool_validation import ToolError
from olga_companion.sidecar import app

TOOL = "fluids_import_tab"
SCHEMA_LIMIT = 4096
BAR = 1e5

CSV_TWO = (
    "P (bar),T (C),ROG,ROHL,VISG,VISHL\n"
    "1,10,1.2,800,1.1e-05,0.002\n"
    "1,30,1.1,790,1.2e-05,0.0015\n"
    "5,10,6.0,810,1.1e-05,0.0021\n"
    "5,30,5.5,800,1.2e-05,0.0016\n"
    "10,10,12,820,1.1e-05,0.0022\n"
    "10,30,11,810,1.2e-05,0.0017\n"
)


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    session_token.boot_token()
    pending_approvals.revoke_all()
    yield root
    pending_approvals.revoke_all()


@pytest.fixture
def root(_workspace: Path) -> Path:
    return _workspace


@pytest.fixture
def gen() -> int:
    return workspace.context_generation()


def _csv(root: Path, text: str = CSV_TWO, name: str = "props.csv") -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def _codes(result: dict[str, Any]) -> set[str]:
    return {issue["code"] for issue in result["issues"]}


def _parse(text: str, tmp_path: Path):
    from olga_companion import tab_compare

    path = tmp_path / "roundtrip.tab"
    path.write_text(text, encoding="utf-8")
    return tab_compare._parse(path)


# ------------------------------------------------------------------ the module


def test_a_complete_grid_becomes_a_standard_two_phase_table(root: Path, tmp_path: Path) -> None:
    result = tab_import.build(_csv(root), fluid_label="NEUTRAL-A")
    assert result["ok"] is True, result["issues"]
    assert result["issues"] == []
    text = result["text"]
    assert text.startswith('PVTTABLE LABEL = "NEUTRAL-A",PHASE = TWO')
    assert "MESHTYPE = STANDARD" in text
    assert "PRESSURE = ( 100000, 500000, 1000000 ) PA" in text
    assert "TEMPERATURE = ( 10, 30 ) C" in text
    assert "COLUMNS = ( PT, TM, ROG, ROHL, VISG, VISHL )" in text
    assert text.count("PVTTABLE POINT") == 6
    summary = result["summary"]
    assert (summary["pressure_points"], summary["temperature_points"], summary["points"]) == (3, 2, 6)
    assert summary["phase"] == "TWO"
    assert summary["columns"] == ["ROG", "ROHL", "VISG", "VISHL"]
    assert summary["calculated"] is False


def test_the_produced_text_parses_back_with_the_toolkit_parser_value_for_value(root: Path, tmp_path: Path) -> None:
    result = tab_import.build(_csv(root), fluid_label="NEUTRAL-A")
    parsed = _parse(result["text"], tmp_path)
    assert parsed.point_rows is not None and len(parsed.point_rows) == 6
    assert parsed.pressure_grid == [1 * BAR, 5 * BAR, 10 * BAR]
    assert parsed.temperature_grid == [10.0, 30.0]
    assert parsed.columns == ["PT", "TM", "ROG", "ROHL", "VISG", "VISHL"]
    first = parsed.point_rows[0]
    assert first == [100000.0, 10.0, 1.2, 800.0, 1.1e-05, 0.002]
    assert parsed.point_rows[-1] == [1000000.0, 30.0, 11.0, 810.0, 1.2e-05, 0.0017]


def test_the_toolkit_validator_accepts_the_produced_file(root: Path) -> None:
    result = tab_import.build(_csv(root), fluid_label="NEUTRAL-A")
    assert result["ok"] is True
    assert result["summary"]["validator_errors"] == 0


def test_pressure_in_bar_and_temperature_in_kelvin_are_converted_to_pa_and_c(root: Path, tmp_path: Path) -> None:
    csv_text = (
        "Pressure (bar),T (K),ROG,ROHL\n"
        "2,283.15,1,800\n2,303.15,2,801\n3,283.15,3,802\n3,303.15,4,803\n"
    )
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is True, result["issues"]
    parsed = _parse(result["text"], tmp_path)
    assert parsed.pressure_grid == [200000.0, 300000.0]
    assert parsed.temperature_grid == [10.0, 30.0]
    assert "bar" in json.dumps(result["summary"]["source_units"]).lower()
    assert result["summary"]["source_units"] == {"pressure": "bar", "temperature": "K"}


@pytest.mark.parametrize(
    ("header", "p_values", "t_values", "p_expected", "t_expected"),
    [
        ("psia,degF", (14.5, 29.0), (50, 86), [14.5 * 6894.757293168, 29.0 * 6894.757293168], [10.0, 30.0]),
        ("Pressure (Pa),T (C)", (100000, 200000), (10, 30), [100000.0, 200000.0], [10.0, 30.0]),
        ("P [kPa],Temperature [degC]", (100, 200), (10, 30), [100000.0, 200000.0], [10.0, 30.0]),
        ("P_MPa,T_K", (0.1, 0.2), (283.15, 303.15), [100000.0, 200000.0], [10.0, 30.0]),
    ],
)
def test_pressure_and_temperature_headers_carry_their_unit(
    root: Path, tmp_path: Path, header: str, p_values, t_values, p_expected, t_expected
) -> None:
    rows = "".join(
        f"{p},{t},{1 + i},{800 + i}\n" for i, (p, t) in enumerate((p, t) for p in p_values for t in t_values)
    )
    result = tab_import.build(_csv(root, f"{header},ROG,ROHL\n{rows}"), fluid_label="NEUTRAL-A")
    assert result["ok"] is True, result["issues"]
    parsed = _parse(result["text"], tmp_path)
    assert parsed.pressure_grid == pytest.approx(p_expected, rel=1e-9)
    assert parsed.temperature_grid == pytest.approx(t_expected, abs=1e-9)


def test_a_missing_grid_point_is_named_and_nothing_is_offered(root: Path) -> None:
    lines = CSV_TWO.splitlines()
    del lines[3]  # drops 5 bar, 10 C
    result = tab_import.build(_csv(root, "\n".join(lines) + "\n"), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert result["text"] is None
    assert "missing_point" in _codes(result)
    missing = next(issue for issue in result["issues"] if issue["code"] == "missing_point")
    assert missing["params"]["count"] == 1
    assert missing["params"]["first"] == [500000.0, 10.0]


def test_an_axis_that_does_not_increase_is_refused(root: Path) -> None:
    csv_text = "P (bar),T (C),ROG,ROHL\n1,30,1,800\n1,10,2,801\n5,30,3,802\n5,10,4,803\n"
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "axis_not_increasing" in _codes(result)
    issue = next(issue for issue in result["issues"] if issue["code"] == "axis_not_increasing")
    assert issue["params"]["axis"] == "temperature"


def test_a_duplicate_point_is_refused(root: Path) -> None:
    csv_text = CSV_TWO + "10,30,11,810,1.2e-05,0.0017\n"
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "duplicate_point" in _codes(result)


@pytest.mark.parametrize("cell", ["nan", "inf", "-inf", "abc", ""])
def test_a_property_cell_that_is_not_a_finite_number_is_refused(root: Path, cell: str) -> None:
    csv_text = CSV_TWO.replace("12,820", f"{cell},820")
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert _codes(result) & {"not_a_number", "missing_value"}


def test_a_pressure_without_a_unit_is_refused_not_guessed(root: Path) -> None:
    result = tab_import.build(_csv(root, CSV_TWO.replace("P (bar)", "P")), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "pressure_unit_missing" in _codes(result)


def test_a_temperature_without_a_unit_is_refused_not_guessed(root: Path) -> None:
    result = tab_import.build(_csv(root, CSV_TWO.replace("T (C)", "T")), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "temperature_unit_missing" in _codes(result)


def test_an_unknown_pressure_unit_is_refused(root: Path) -> None:
    result = tab_import.build(_csv(root, CSV_TWO.replace("P (bar)", "P (furlong)")), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "pressure_unit_unknown" in _codes(result)


def test_a_property_in_another_unit_than_olga_si_is_refused_not_rescaled(root: Path) -> None:
    result = tab_import.build(_csv(root, CSV_TWO.replace("ROG,", "ROG (g/cm3),")), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "property_unit_mismatch" in _codes(result)
    # The same unit written differently is the OLGA unit and is accepted.
    same = tab_import.build(_csv(root, CSV_TWO.replace("ROG,", "ROG (kg/m3),")), fluid_label="NEUTRAL-A")
    assert same["ok"] is True, same["issues"]


def test_the_gas_and_liquid_density_columns_are_required(root: Path) -> None:
    csv_text = "P (bar),T (C),VISG\n1,10,1e-5\n1,30,1e-5\n5,10,1e-5\n5,30,1e-5\n"
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "required_column_missing" in _codes(result)


def test_columns_that_are_not_olga_codes_are_listed_and_left_out(root: Path) -> None:
    csv_text = CSV_TWO.replace("P (bar),T (C),", "Point,P (bar),T (C),").replace("\n1,", "\nA,1,").replace("\n5,", "\nB,5,").replace("\n10,", "\nC,10,")
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is True, result["issues"]
    assert result["summary"]["ignored_columns"] == ["Point"]
    assert "Point" not in result["text"]


def test_a_water_column_makes_a_three_phase_table_and_needs_the_water_fraction_the_user_states(
    root: Path, tmp_path: Path
) -> None:
    csv_text = "P (bar),T (C),ROG,ROHL,ROWT,VISWT\n1,10,1,800,999,0.001\n1,30,1,790,992,0.0008\n5,10,6,810,999,0.001\n5,30,5,800,992,0.0008\n"
    csv_path = _csv(root, csv_text)
    refused = tab_import.build(csv_path, fluid_label="NEUTRAL-A")
    assert refused["ok"] is False
    assert "water_fraction_required" in _codes(refused)
    result = tab_import.build(csv_path, fluid_label="NEUTRAL-A", total_water_fraction=0.4)
    assert result["ok"] is True, result["issues"]
    assert "PHASE = THREE" in result["text"]
    assert "TOTWATERFRACTION = ( 0.4 )" in result["text"]
    assert result["summary"]["phase"] == "THREE"
    assert _parse(result["text"], tmp_path).point_rows is not None


def test_a_water_fraction_without_water_columns_is_ignored_for_a_two_phase_table(root: Path) -> None:
    result = tab_import.build(_csv(root), fluid_label="NEUTRAL-A", total_water_fraction=0.4)
    assert result["ok"] is True
    assert "PHASE = TWO" in result["text"] and "TOTWATERFRACTION" not in result["text"]


def test_the_composition_is_written_only_when_the_user_gives_it(root: Path, tmp_path: Path) -> None:
    bare = tab_import.build(_csv(root), fluid_label="NEUTRAL-A")
    assert 'COMPONENTS = ( "NOT_STATED" ), MOLES = ( 1 )' in bare["text"]
    stated = tab_import.build(
        _csv(root), fluid_label="NEUTRAL-A", components=["CO2", "N2"], moles=[0.8, 0.2]
    )
    assert 'COMPONENTS = ( "CO2", "N2" ), MOLES = ( 0.8, 0.2 )' in stated["text"]
    assert [c.strip('"') for c in _parse(stated["text"], tmp_path).components] == ["CO2", "N2"]
    uneven = tab_import.build(_csv(root), fluid_label="NEUTRAL-A", components=["CO2"], moles=[0.5, 0.5])
    assert uneven["ok"] is False and "composition_invalid" in _codes(uneven)


def test_one_pressure_or_one_temperature_is_not_a_grid(root: Path) -> None:
    csv_text = "P (bar),T (C),ROG,ROHL\n1,10,1,800\n1,30,1,790\n"
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "grid_too_small" in _codes(result)


def test_a_non_positive_pressure_is_refused(root: Path) -> None:
    csv_text = "P (bar),T (C),ROG,ROHL\n0,10,1,800\n0,30,1,790\n5,10,1,800\n5,30,1,790\n"
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "pressure_not_positive" in _codes(result)


def test_a_bad_label_is_refused(root: Path) -> None:
    with pytest.raises(fluid_table.FluidTableError):
        tab_import.build(_csv(root), fluid_label="has space")


def test_a_semicolon_csv_with_decimal_commas_is_read(root: Path) -> None:
    csv_text = CSV_TWO.replace(",", ";").replace("1.1e-05", "1,1e-05").replace("1.2", "1,2")
    result = tab_import.build(_csv(root, csv_text), fluid_label="NEUTRAL-A")
    assert result["ok"] is True, result["issues"]


def test_an_xlsx_workbook_is_read_like_a_csv(root: Path, tmp_path: Path) -> None:
    rows = [line.split(",") for line in CSV_TWO.strip().splitlines()]

    def cell(ref: str, value: str) -> str:
        try:
            float(value)
            return f'<c r="{ref}"><v>{value}</v></c>'
        except ValueError:
            return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'

    body = "".join(
        f'<row r="{r}">' + "".join(cell(f"{'ABCDEF'[c]}{r}", v) for c, v in enumerate(row)) + "</row>"
        for r, row in enumerate(rows, start=1)
    )
    path = root / "props.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Props" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{body}</sheetData></worksheet>",
        )
    result = tab_import.build(path, fluid_label="NEUTRAL-A")
    assert result["ok"] is True, result["issues"]
    assert _parse(result["text"], tmp_path).point_rows is not None
    assert result["summary"]["sheet"] == "Props"


def test_a_file_that_is_not_csv_or_xlsx_is_refused(root: Path) -> None:
    path = root / "props.txt"
    path.write_text(CSV_TWO, encoding="utf-8")
    with pytest.raises(tab_import.TabImportError):
        tab_import.build(path, fluid_label="NEUTRAL-A")


def test_preview_reads_only_and_returns_the_summary_and_a_head_of_the_file(root: Path) -> None:
    before = sorted(p.name for p in root.iterdir())
    source = _csv(root)
    result = tab_import.preview(source, fluid_label="NEUTRAL-A")
    assert result["ok"] is True
    assert result["writes_nothing"] is True
    assert "text" not in result
    assert result["text_head"].startswith('PVTTABLE LABEL = "NEUTRAL-A"')
    assert len(result["tab_sha256"]) == 64
    assert sorted(p.name for p in root.iterdir()) == sorted([*before, "props.csv"])


def test_the_round_trip_catches_a_table_the_parser_would_reject(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tab_import, "_render", lambda *a, **k: "PVTTABLE LABEL = \"X\",PHASE = TWO, MESHTYPE = STANDARD\n")
    result = tab_import.build(_csv(root), fluid_label="NEUTRAL-A")
    assert result["ok"] is False
    assert "roundtrip_failed" in _codes(result)
    assert result["text"] is None


def test_write_new_never_overwrites(root: Path) -> None:
    target = root / "out.tab"
    tab_import.write_new(target, "A\n")
    assert target.read_text(encoding="utf-8") == "A\n"
    with pytest.raises(tab_import.TabImportError):
        tab_import.write_new(target, "B\n")
    assert target.read_text(encoding="utf-8") == "A\n"


def test_the_released_path_never_imports_the_unreleased_engine() -> None:
    source = (Path(tab_import.__file__)).read_text(encoding="utf-8")
    assert "pvt_engine" not in source
    assert "native_tab" not in source


# ------------------------------------------------------------------ the preview route


@pytest.fixture
def http(root: Path) -> TestClient:
    return TestClient(app)


def test_the_preview_route_summarises_a_workspace_table_and_writes_nothing(http: TestClient, root: Path) -> None:
    _csv(root)
    response = http.post("/api/fluids/tab-import/preview", json={"path": "props.csv", "fluid_label": "NEUTRAL-A"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["summary"]["points"] == 6
    assert body["writes_nothing"] is True
    assert sorted(p.name for p in root.iterdir()) == ["props.csv"]


def test_the_preview_route_reports_issues_instead_of_failing(http: TestClient, root: Path) -> None:
    _csv(root, CSV_TWO.replace("P (bar)", "P"))
    body = http.post("/api/fluids/tab-import/preview", json={"path": "props.csv", "fluid_label": "NEUTRAL-A"}).json()
    assert body["ok"] is False
    assert body["issues"][0]["code"] == "pressure_unit_missing"


def test_the_preview_route_refuses_a_path_outside_the_workspace(http: TestClient, root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.csv"
    outside.write_text(CSV_TWO, encoding="utf-8")
    response = http.post("/api/fluids/tab-import/preview", json={"path": str(outside), "fluid_label": "NEUTRAL-A"})
    assert response.status_code == 400


def test_the_preview_route_has_no_write_twin(http: TestClient) -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/fluids/tab-import/preview" in paths
    assert not [path for path in paths if path.startswith("/api/fluids/tab-import") and path != "/api/fluids/tab-import/preview"]


# ------------------------------------------------------------------ the approval-gated tool


def _args(**extra: Any) -> dict[str, Any]:
    return {"source_rel": "props.csv", "tab_rel": "props.tab", "fluid_label": "NEUTRAL-A", **extra}


def _approved(args: dict[str, Any], generation: int) -> dict[str, Any]:
    payload = tools.approval_payload(TOOL, args)
    token = approvals.mint(TOOL, payload, context_generation=generation)["token"]
    return {**args, "approval_token": token, "idempotency_key": "k" * 32}


def test_the_tool_is_a_closed_approval_gated_side_effect() -> None:
    tool = tools.TOOLS[TOOL]
    assert tool.side_effect is True
    assert tool.parameters["additionalProperties"] is False
    assert {"source_rel", "tab_rel", "fluid_label", "approval_token", "idempotency_key"} <= set(tool.parameters["required"])
    spec = next(item for item in tools.tool_specs() if item["name"] == TOOL)
    assert "approval_token" not in spec["parameters"]["properties"]
    assert "idempotency_key" not in spec["parameters"]["required"]
    assert len(json.dumps(spec)) <= SCHEMA_LIMIT


def test_the_tool_never_joins_a_plan() -> None:
    assert TOOL in plan_model.NEVER_IN_PLAN
    with pytest.raises(ToolError, match=TOOL):
        tools.approval_payload("action_plan", {"steps": [{"kind": TOOL, "args": _args()}]})


def test_the_tool_exists_without_the_unreleased_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLGA_COMPANION_NATIVE_TAB", raising=False)
    assert TOOL in tools.TOOLS
    assert "native" not in " ".join(next(s for s in tools.tool_specs() if s["name"] == TOOL)["description"].split()).lower()


def test_no_card_is_offered_for_a_table_that_would_not_import(root: Path) -> None:
    _csv(root, CSV_TWO.replace("P (bar)", "P"))
    with pytest.raises(ToolError, match="pressure"):
        tools.approval_payload(TOOL, _args())
    assert not (root / "props.tab").exists()


def test_dispatch_without_an_approval_writes_nothing(root: Path) -> None:
    _csv(root)
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, _args())
    assert not (root / "props.tab").exists()


def test_dispatch_writes_the_approved_table_once_and_the_validator_passes(root: Path, gen: int, tmp_path: Path) -> None:
    _csv(root)
    result = tools.dispatch(TOOL, _approved(_args(), gen))
    target = root / "props.tab"
    assert result["ok"] is True
    assert result["tab_rel"] == "props.tab"
    assert result["fluid_label"] == "NEUTRAL-A"
    assert result["calculated"] is False
    assert result["validator"]["valid"] is True
    assert result["points"] == 6
    assert fluid_table.pickup_tab(str(target), "NEUTRAL-A")["valid"] is True
    assert _parse(target.read_text(encoding="utf-8"), tmp_path).point_rows is not None
    assert "approval_token" not in json.dumps(result)


def test_the_approval_is_single_use(root: Path, gen: int) -> None:
    _csv(root)
    approved = _approved(_args(), gen)
    tools.dispatch(TOOL, approved)
    (root / "props.tab").unlink()
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, approved)
    assert not (root / "props.tab").exists()


def test_an_existing_destination_is_refused_and_left_untouched(root: Path) -> None:
    _csv(root)
    (root / "props.tab").write_text("owner file\n", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        tools.approval_payload(TOOL, _args())
    assert (root / "props.tab").read_text(encoding="utf-8") == "owner file\n"


def test_a_file_that_appears_after_the_card_is_never_overwritten(root: Path, gen: int) -> None:
    _csv(root)
    approved = _approved(_args(), gen)
    (root / "props.tab").write_text("owner file\n", encoding="utf-8")
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, approved)
    assert (root / "props.tab").read_text(encoding="utf-8") == "owner file\n"


def test_a_source_that_changes_after_the_card_is_not_written(root: Path, gen: int) -> None:
    _csv(root)
    approved = _approved(_args(), gen)
    _csv(root, CSV_TWO.replace("12,820", "13,820"))
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, approved)
    assert not (root / "props.tab").exists()


@pytest.mark.parametrize("tab_rel", ["../outside.tab", "/tmp/outside.tab", "sub/../../outside.tab"])
def test_a_destination_outside_the_workspace_is_refused(root: Path, tab_rel: str) -> None:
    _csv(root)
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, _args(tab_rel=tab_rel))
    assert not (root.parent / "outside.tab").exists()


@pytest.mark.parametrize("source_rel", ["../props.csv", "/etc/passwd.csv", "sub/../../props.csv"])
def test_a_source_outside_the_workspace_is_refused(root: Path, tmp_path: Path, source_rel: str) -> None:
    (tmp_path / "props.csv").write_text(CSV_TWO, encoding="utf-8")
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, _args(source_rel=source_rel))


def test_a_symlink_that_leaves_the_workspace_is_refused(root: Path, tmp_path: Path) -> None:
    _csv(root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        os.symlink(elsewhere, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable here")
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, _args(tab_rel="link/props.tab"))
    assert not (elsewhere / "props.tab").exists()


@pytest.mark.parametrize("tab_rel", ["props.txt", "props", "props.mfl", ""])
def test_only_a_tab_destination_is_accepted(root: Path, tab_rel: str) -> None:
    _csv(root)
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, _args(tab_rel=tab_rel))


def test_a_missing_folder_is_refused_without_creating_it(root: Path) -> None:
    _csv(root)
    with pytest.raises(ToolError, match="folder"):
        tools.approval_payload(TOOL, _args(tab_rel="nope/props.tab"))
    assert not (root / "nope").exists()


def test_a_source_that_is_not_csv_or_xlsx_is_refused(root: Path) -> None:
    (root / "props.txt").write_text(CSV_TWO, encoding="utf-8")
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, _args(source_rel="props.txt"))


def test_a_missing_source_is_refused(root: Path) -> None:
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, _args())


def test_one_card_click_writes_the_table_through_the_real_approval_route(root: Path, gen: int) -> None:
    _csv(root)
    session_id = history.new_session("tab-import")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args=_args(), call_id="s-1",
        context_generation=gen, session_id=session_id,
    )
    body = approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="s-1", context_generation=gen
    )
    assert (root / "props.tab").is_file()
    assert body["result"]["validator"]["valid"] is True


# ------------------------------------------------------------------ the card


def test_the_card_shows_what_will_be_written_in_english(root: Path) -> None:
    _csv(root)
    shown = approval_display.build(TOOL, _args(), locale="en")
    rows = {row["key"]: row for row in shown["fields"]}
    assert rows["file"]["value"] == "props.tab"
    assert rows["source_file"]["value"] == "props.csv"
    assert rows["label"]["value"] == "NEUTRAL-A"
    assert rows["pressure_points"]["value"] == "3"
    assert rows["temperature_points"]["value"] == "2"
    assert rows["point_count"]["value"] == "6"
    assert rows["columns"]["value"] == "ROG, ROHL, VISG, VISHL"
    assert (rows["pressure_range"]["value"], rows["pressure_range"]["unit"]) == ("100000 – 1000000", "Pa")
    assert (rows["temperature_range"]["value"], rows["temperature_range"]["unit"]) == ("10 – 30", "degC")
    kind = rows["table_kind"]["value"]
    assert "as given" in kind and "nothing is calculated" in kind
    assert "approval_token" not in json.dumps(shown)


def test_the_card_is_natural_korean_for_a_korean_locale(root: Path) -> None:
    _csv(root)
    shown = approval_display.build(TOOL, _args(), locale="ko")
    kind = next(row["value"] for row in shown["fields"] if row["key"] == "table_kind")
    assert "그대로" in kind and "계산" in kind
    assert "calculated" not in kind


def test_the_card_is_refused_for_the_same_requests_the_tool_refuses(root: Path) -> None:
    _csv(root)
    (root / "props.tab").write_text("owner file\n", encoding="utf-8")
    with pytest.raises(ToolError):
        approval_display.build(TOOL, _args(), locale="en")
