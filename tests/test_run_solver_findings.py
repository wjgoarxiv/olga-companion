"""Failed-run solver findings stay bounded and do not apply a suggestion."""

from pathlib import Path

from olga_companion.run_solver_findings import attach_solver_findings, findings_for_out

FIXTURE = Path(__file__).parent / "fixtures" / "out" / "dtmin_hit.out"


def test_dtmin_hit_fixture_becomes_a_bounded_finding() -> None:
    findings = findings_for_out(str(FIXTURE))

    assert findings
    assert findings[0]["code"] == "DTMIN_HIT"
    assert "최소 시간 간격" in findings[0]["message"]
    assert findings[0]["suggestion"]
    assert "C:\\Secret" not in findings[0]["message"]
    assert "C:\\Secret" not in (findings[0]["evidence"] or "")
    assert len(findings) <= 8


def test_failed_status_carries_findings_and_a_clean_run_does_not(tmp_path: Path) -> None:
    out = tmp_path / "case.out"
    out.write_text(FIXTURE.read_text(), encoding="utf-8")
    failed = {
        "state": "failed",
        "outputs": [{"name": "case.out", "path": str(out), "suffix": ".out"}],
        "failure": {"code": "native_process_failed", "title": "OLGA process failed"},
    }
    attach_solver_findings(failed)
    assert failed["solver_findings"][0]["code"] == "DTMIN_HIT"
    assert failed["failure"]["solver_findings"][0]["code"] == "DTMIN_HIT"

    running = {"state": "running", "outputs": failed["outputs"], "failure": None}
    attach_solver_findings(running)
    assert running["solver_findings"] == []
