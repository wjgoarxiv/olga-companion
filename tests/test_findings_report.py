"""Findings Markdown cites evaluation verdicts and figure paths."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

import pytest

from olga_companion.agent import session_token, tools
from olga_companion.genkey_static import file_sha256
from olga_companion.reports import findings_report
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures"
GENKEY = FIXTURES / "cases" / "simple_pipeline.genkey"
TPL = FIXTURES / "results" / "fixture.tpl"


def _verdicts(tpl: Path) -> list[dict]:
    return [
        {
            "criterion": "pressure_drop",
            "verdict": "FAIL",
            "source_file": str(tpl),
            "source_sha256": file_sha256(tpl),
            "source_mutated": False,
            "variables": ["PT"],
            "timestep": "all",
            "mapping": {"inlet_position": "INLET", "outlet_position": "OUTLET"},
            "formula": "drop(t) = PT_inlet(t) - PT_outlet(t)",
            "threshold": {"max_drop": 100000.0},
            "measured": {"drop_max": 2060000.0},
            "command": {"tool": "evaluation.pressure_drop"},
        },
        {
            "criterion": "liqc",
            "status": "input_required",
            "missing": ["limit"],
        },
    ]


def test_findings_report_lists_verdicts_citations_and_figures() -> None:
    figure = "figures/pressure-drop.png"
    report = findings_report(str(GENKEY), str(TPL), _verdicts(TPL), [figure])
    text = report["markdown"]
    liqc = text.split("### liqc", 1)[1].split("###", 1)[0]

    assert report["filename"].endswith(".md")
    assert "## 판정 결과" in text
    assert "pressure_drop" in text
    assert "FAIL" in text
    assert "drop(t) = PT_inlet(t) - PT_outlet(t)" in text
    assert file_sha256(TPL) in text
    assert str(TPL.resolve()) in text or str(TPL) in text
    assert "## Sources" in text
    assert file_sha256(GENKEY) in text
    assert f"![]({figure})" in text
    assert "입력 필요" in liqc
    assert "PASS" not in liqc
    assert "FAIL" not in liqc
    assert "report" not in report


def test_findings_route_requires_a_session_token(tmp_path: Path, monkeypatch) -> None:
    exports = tmp_path / "exports"
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("olga_companion.reports.exports_root", lambda: exports)
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    case = tmp_path / GENKEY.name
    results = tmp_path / TPL.name
    shutil.copy2(GENKEY, case)
    shutil.copy2(TPL, results)
    body = {
        "case_file": case.name,
        "results_file": results.name,
        "verdicts": _verdicts(results),
        "figures": ["figures/pressure-drop.png"],
    }
    client = TestClient(app)
    headers = {"X-Session-Token": session_token.boot_token()}

    denied = client.post("/api/reports/findings", json=body)
    assert denied.status_code == 401

    accepted = client.post("/api/reports/findings", json=body, headers=headers)
    assert accepted.status_code == 200
    payload = accepted.json()
    assert "pressure_drop" in payload["markdown"]
    assert file_sha256(results) in payload["markdown"]
    assert "figures/pressure-drop.png" in payload["markdown"]
    assert "입력 필요" in payload["markdown"]
    assert payload["filename"].endswith(".md")
    assert list(tmp_path.glob("*.md")) == []

    artifact = Path(payload["artifact"])
    assert artifact.is_file()
    assert exports.resolve() in artifact.resolve().parents
    assert artifact.name == payload["filename"]
    assert artifact.read_text(encoding="utf-8") == payload["markdown"]

    destination = tmp_path / "chosen" / "kept.md"
    destination.parent.mkdir()
    observed: dict[str, object] = {}

    def cancelled_dialog(*_args, **kwargs):
        observed["suggested_name"] = kwargs.get("suggested_name")
        return {"status": "cancelled"}

    monkeypatch.setattr("olga_companion.native_dialogs.show_dialog", cancelled_dialog)
    cancelled = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "findings-cancel", "artifact": payload["artifact"]},
        headers=headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert observed["suggested_name"] == payload["filename"]
    assert not destination.exists()

    def selected_dialog(*_args, **kwargs):
        observed["suggested_name"] = kwargs.get("suggested_name")
        return {"status": "selected", "path": str(destination)}

    monkeypatch.setattr("olga_companion.native_dialogs.show_dialog", selected_dialog)
    saved = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "findings-save", "artifact": payload["artifact"]},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["basename"] == destination.name
    assert str(destination) not in saved.text
    assert destination.read_text(encoding="utf-8") == payload["markdown"]


def test_report_markdown_tool_accepts_verdicts_and_figures(tmp_path: Path, monkeypatch) -> None:
    exports = tmp_path / "exports"
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("olga_companion.reports.exports_root", lambda: exports)
    case = tmp_path / GENKEY.name
    shutil.copy2(GENKEY, case)
    verdicts = [
        {
            "criterion": "pressure_drop",
            "verdict": "FAIL",
            "formula": "drop(t) = PT_inlet(t) - PT_outlet(t)",
            "source_file": "fixture.tpl",
            "source_sha256": "abc123",
            "measured": {"drop_max": 1},
        }
    ]
    figures = ["figures/pressure-drop.png"]

    result = tools.dispatch(
        "report_markdown",
        {"genkey": case.name, "verdicts": verdicts, "figures": figures},
    )

    text = Path(result["report"]).read_text(encoding="utf-8")
    assert "pressure_drop" in text
    assert "drop(t) = PT_inlet(t) - PT_outlet(t)" in text
    assert "figures/pressure-drop.png" in text
    assert "## 판정 결과" in text


def test_report_markdown_tool_rejects_an_unknown_top_level_key(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["report_markdown"],
        "handler",
        lambda args: calls.append(args) or {},
    )

    with pytest.raises(tools.ToolError, match="unknown"):
        tools.dispatch("report_markdown", {"genkey": "case.genkey", "note": "extra"})

    assert calls == []


def test_zero_verdict_report_states_skipped_with_receipt_variables_and_sha() -> None:
    report = findings_report(str(GENKEY), str(TPL), [], ["figures/pressure-drop.png"], ["PT", "TM"])
    text = report["markdown"]
    assert "판정: 입력 필요(사용자가 생략)" in text
    assert "## 변수" in text
    assert "- PT" in text
    assert "## 그림" in text
    assert "## Sources" in text
    assert file_sha256(TPL) in text
    assert file_sha256(GENKEY) in text


def test_zero_verdict_report_names_run_id_when_given() -> None:
    report = findings_report(str(GENKEY), str(TPL), [], [], ["PT"], run_id="b553b7490451")
    assert "실행: `b553b7490451`" in report["markdown"]
    assert "판정: 입력 필요(사용자가 생략)" in report["markdown"]
