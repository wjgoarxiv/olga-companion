"""N5: two workspace cases compared key by key; formatting never shows as a change."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import case_diff
from olga_companion.examples import install_example
from olga_companion.sidecar import app

client = TestClient(app)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    return root


def _case(ws: Path) -> Path:
    return ws / install_example("valve-shut-in")["case_rel"]


def test_a_case_against_itself_is_the_same(ws: Path) -> None:
    case = _case(ws)
    assert case_diff.diff_cases(case, case)["same"] is True


def test_formatting_comments_and_key_order_are_not_changes(ws: Path) -> None:
    text = _case(ws).read_text(encoding="utf-8")
    reformatted = "! a comment\n" + text.replace(
        "TREND DTPLOT=60 s", "TREND \\\n   DTPLOT=60 s ! plot step"
    ).replace("ENDTIME=3600 s, MINDT=0.001 s", "MINDT=0.001 s,   ENDTIME=3600 s").replace("(0, 900, 960, 2100, 2160)", "(0,900,960,2100,2160)")
    assert reformatted != text
    assert case_diff.diff_texts(text, reformatted)["same"] is True


def test_a_changed_value_names_its_component_record_and_key(ws: Path) -> None:
    text = _case(ws).read_text(encoding="utf-8")
    edited = text.replace("PRESSURE=200000 Pa", "PRESSURE=500000 Pa")
    result = case_diff.diff_texts(text, edited)
    assert result["changed"] == [{
        "component": "OUTLET", "keyword": "PARAMETERS", "label": "OUTLET",
        "key": "PRESSURE", "before": "200000 Pa", "after": "500000 Pa",
    }]
    assert result["added"] == [] and result["removed"] == []


def test_records_without_a_label_are_matched_by_order(ws: Path) -> None:
    text = _case(ws).read_text(encoding="utf-8")
    result = case_diff.diff_texts(text, text.replace("ENDTIME=3600 s", "ENDTIME=7200 s"))
    assert [(row["keyword"], row["label"], row["key"], row["after"]) for row in result["changed"]] == [
        ("INTEGRATION", "#1", "ENDTIME", "7200 s"),
    ]


def test_an_added_and_a_removed_record_are_listed(ws: Path) -> None:
    text = _case(ws).read_text(encoding="utf-8")
    edited = text.replace('POSITION LABEL="POS_MAIN_1", PIPE=UPSTREAM, SECTION=1\n', "").replace(
        "ENDCASE", 'MATERIAL LABEL="STEEL", DENSITY=7850 kg/m3\nENDCASE'
    )
    result = case_diff.diff_texts(text, edited)
    assert {(r["keyword"], r["label"]) for r in result["removed"]} == {("POSITION", "POS_MAIN_1")}
    assert {(r["keyword"], r["label"]) for r in result["added"]} == {("MATERIAL", "STEEL")}


def test_the_route_compares_two_workspace_cases_and_writes_nothing(ws: Path) -> None:
    case = _case(ws)
    other = case.with_name("other.genkey")
    other.write_text(case.read_text(encoding="utf-8").replace("ROUGHNESS=0.00005 m", "ROUGHNESS=0.0001 m", 1), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in ws.rglob("*") if path.is_file()}
    response = client.get("/api/case-diff", params={"a": case.relative_to(ws).as_posix(), "b": other.relative_to(ws).as_posix()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["same"] is False
    assert [(r["label"], r["key"], r["before"], r["after"]) for r in body["changed"]] == [("UPSTREAM", "ROUGHNESS", "0.00005 m", "0.0001 m")]
    assert {path.name: path.read_bytes() for path in ws.rglob("*") if path.is_file()} == before


def test_the_route_refuses_a_case_outside_the_workspace(ws: Path, tmp_path: Path) -> None:
    case = _case(ws)
    outside = tmp_path / "outside.genkey"
    outside.write_text("CASE\n", encoding="utf-8")
    response = client.get("/api/case-diff", params={"a": case.relative_to(ws).as_posix(), "b": str(outside)})
    assert response.status_code == 400


def test_deleting_the_first_unlabelled_record_reads_as_a_deletion() -> None:
    """Review: records without a LABEL are lined up by content, not by position alone."""
    before = "TREND DTPLOT=10 s\nTREND DTPLOT=20 s\nTREND DTPLOT=30 s\n"
    after = "TREND DTPLOT=20 s\nTREND DTPLOT=30 s\n"
    diff = case_diff.diff_texts(before, after)
    assert diff["changed"] == []
    assert diff["added"] == []
    assert diff["removed"] == [{"component": None, "keyword": "TREND", "label": "#1"}]


def test_an_edited_unlabelled_record_between_two_others_is_a_change() -> None:
    before = "TREND DTPLOT=10 s\nTREND DTPLOT=20 s\nTREND DTPLOT=30 s\n"
    after = "TREND DTPLOT=10 s\nTREND DTPLOT=25 s\nTREND DTPLOT=30 s\n"
    diff = case_diff.diff_texts(before, after)
    assert [(r["label"], r["key"], r["before"], r["after"]) for r in diff["changed"]] == [("#2", "DTPLOT", "20 s", "25 s")]
    assert diff["removed"] == [] and diff["added"] == []


def test_more_than_400_differences_are_cut_and_say_so() -> None:
    before = "".join(f'PIPE LABEL="P{i}", DIAMETER=0.2 m\n' for i in range(450))
    after = "".join(f'PIPE LABEL="P{i}", DIAMETER=0.3 m\n' for i in range(450))
    diff = case_diff.diff_texts(before, after)
    assert diff["truncated"] is True
    assert len(diff["changed"]) == 400
