from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import olga_companion.reports as reports_module
from olga_companion.genkey_static import file_sha256
from olga_companion.reports import compare_cases, generate_figure, markdown_report, reports_toolkit_status
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures" / "results"
TPL = FIXTURES / "fixture.tpl"
EVAL_PPL = FIXTURES / "eval_case.ppl"
SAMPLE_GENKEY = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(
    not (reports_toolkit_status()["available"] and SAMPLE_GENKEY.exists()),
    reason="OLGA report toolkit scripts or sample cases are unavailable",
)


@pytest.fixture(autouse=True)
def exports_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "exports"
    root.mkdir()
    monkeypatch.setattr(reports_module, "exports_root", lambda: root)
    return root


def test_markdown_report_cites_source_files_and_hashes(exports_tmp: Path) -> None:
    genkey_hash = file_sha256(SAMPLE_GENKEY)
    result = markdown_report(str(SAMPLE_GENKEY))
    assert result["ok"] is True
    report = Path(result["report"])
    assert report.is_relative_to(exports_tmp)
    text = report.read_text(encoding="utf-8")
    assert "OLGA Analysis Report" in text
    assert "## Sources" in text
    assert str(SAMPLE_GENKEY.resolve()) in text  # trust boundary resolves symlinks
    assert genkey_hash in text
    assert file_sha256(SAMPLE_GENKEY) == genkey_hash
    assert result["sources"][0]["mutated"] is False


def test_markdown_report_flags_embedded_tool_failures(
    exports_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # report_generator can embed a traceback in the report while exiting 0; that report
    # must never read as ok (SAFETY_GATES misleading-success prevention). The toolkit's
    # summarizer no longer crashes on this fixture, so the marker is injected: the gate
    # must not depend on a particular toolkit bug being present.
    monkeypatch.setattr(reports_module, "FAILURE_MARKERS", ("OLGA Analysis Report",))

    result = markdown_report(str(SAMPLE_GENKEY), results=str(TPL))

    assert result["command"]["exit_code"] == 0
    assert result["ok"] is False
    assert result["embedded_failures"] == ["OLGA Analysis Report"]
    assert result["report"] is not None, "artifact stays available as evidence"
    text = Path(result["report"]).read_text(encoding="utf-8")
    assert "## Sources" in text
    assert str(TPL.resolve()) in text


def test_figure_bundle_produces_pngs(exports_tmp: Path) -> None:
    profile = generate_figure("hol-profile", str(EVAL_PPL), branch="Pipeline")
    assert profile["ok"] is True
    assert Path(profile["figure"]).is_relative_to(exports_tmp)
    assert Path(profile["figure"]).read_bytes()[:4] == b"\x89PNG"

    timeseries = generate_figure("liqc-timeseries", str(TPL), branch="PIPELINE")
    assert timeseries["ok"] is True
    assert Path(timeseries["figure"]).exists()


def test_unknown_figure_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="figure kind"):
        generate_figure("nonsense", str(EVAL_PPL), branch="Pipeline")


def test_failed_figure_leaves_no_orphan_export_dir(exports_tmp: Path) -> None:
    result = generate_figure("hol-profile", str(EVAL_PPL), branch="NO_SUCH_BRANCH")
    assert result["ok"] is False
    assert result["figure"] is None
    assert not list((exports_tmp / "reports").glob("*")), "failed runs must not leave orphan dirs"


def test_compare_package_contains_both_case_labels(exports_tmp: Path) -> None:
    result = compare_cases([str(TPL), str(TPL)], labels=["caseA", "caseB"], variables=["PT"])
    assert result["ok"] is True
    labels = {row["label"] for row in result["comparison"]}
    assert labels == {"caseA", "caseB"}
    for row in result["comparison"]:
        assert row["variable"] == "PT"
    assert len(result["sources"]) == 2
    assert all(entry["mutated"] is False for entry in result["sources"])


def test_compare_requires_two_files() -> None:
    with pytest.raises(ValueError, match="at least two"):
        compare_cases([str(TPL)], labels=["only"], variables=["PT"])


def test_compare_rejects_ppl_inputs() -> None:
    # The comparator's .ppl mode ignores --json, so .ppl comparison is not offered.
    with pytest.raises(ValueError, match="Only .tpl"):
        compare_cases([str(EVAL_PPL), str(EVAL_PPL)], labels=["a", "b"], variables=["HOL"])


def test_report_trust_boundaries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="File not found"):
        markdown_report(str(tmp_path / "missing.genkey"))
    with pytest.raises(ValueError, match="Invalid"):
        compare_cases([str(TPL), str(TPL)], labels=["ok", "bad label;rm"], variables=["PT"])


def test_reports_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    genkey = tmp_path / SAMPLE_GENKEY.name
    ppl = tmp_path / EVAL_PPL.name
    tpl = tmp_path / TPL.name
    shutil.copy2(SAMPLE_GENKEY, genkey)
    shutil.copy2(EVAL_PPL, ppl)
    shutil.copy2(TPL, tpl)
    client = TestClient(app)

    markdown = client.post("/api/reports/markdown", json={"genkey": str(genkey)})
    assert markdown.status_code == 200
    assert markdown.json()["ok"] is True

    figure = client.post("/api/reports/figure", json={"kind": "hol-profile", "file": str(ppl), "branch": "Pipeline"})
    assert figure.status_code == 200
    assert figure.json()["ok"] is True

    compare = client.post(
        "/api/reports/compare",
        json={"files": [str(tpl), str(tpl)], "labels": ["caseA", "caseB"], "variables": ["PT"]},
    )
    assert compare.status_code == 200
    assert compare.json()["ok"] is True

    bad = client.post("/api/reports/markdown", json={"genkey": str(tmp_path / "missing.genkey")})
    assert bad.status_code == 400


@pytest.mark.parametrize("marker", reports_module.FAILURE_MARKERS)
def test_every_real_failure_marker_is_detected_in_an_exit_zero_report(marker: str) -> None:
    # Each marker is a real shape of toolkit failure text; removing one must break this.
    assert reports_module.embedded_failure_markers(f"# Report\n{marker} something broke\n") == [marker]


def test_a_clean_report_has_no_embedded_failure() -> None:
    assert reports_module.embedded_failure_markers("# Report\nAll sections rendered.\n") == []
