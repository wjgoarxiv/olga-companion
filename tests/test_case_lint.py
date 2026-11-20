"""N2: warn-only checks on the exact .genkey, and which keys the app can change.

Checks never edit a case or block a run. Good cases give no warning; each rule has a case
that triggers it; a value the checks cannot read for sure gives no warning.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import case_lint
from olga_companion.examples import install_example
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures" / "cases"
CATALOG = Path(__file__).resolve().parents[1] / "resources" / "examples" / "catalog.json"

GOOD_PIPE = 'PIPE LABEL="P1", ROUGHNESS=0.00005 m, NSEGMENT=2, LSEGMENT=(50, 50) m, DIAMETER=0.2 m\n'
GOOD_INTEGRATION = "INTEGRATION ENDTIME=3600 s, MAXDT=10 s, MINDT=0.001 s, DTSTART=1 s\n"


def _rules(text: str) -> list[str]:
    return [warning["rule"] for warning in case_lint.lint_text(text)]


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    return root


def test_every_bundled_example_gives_no_warning(ws: Path) -> None:
    ids = [item["id"] for item in json.loads(CATALOG.read_text(encoding="utf-8"))["examples"]]
    assert len(ids) >= 9
    for example_id in ids:
        case = ws / install_example(example_id)["case_rel"]
        assert case_lint.lint_case(case) == [], example_id


def test_the_good_fixtures_give_no_warning() -> None:
    for name in ("simple_pipeline.genkey", "second_pipeline.genkey"):
        assert case_lint.lint_case(FIXTURES / name) == [], name


def test_the_broken_fixture_is_caught() -> None:
    warnings = case_lint.lint_case(FIXTURES / "intentionally_broken.genkey")
    assert [w["rule"] for w in warnings] == ["dtstart_above_maxdt", "diameter_not_positive", "segment_not_positive"]
    assert warnings[0]["values"] == {"value": 200.0, "limit": 100.0, "unit": "s"}
    assert warnings[1]["values"]["label"] == "Pipe_1"


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("OPTIONS STEADYSTATE=ON\n" + GOOD_PIPE, "endtime_missing"),
        ("INTEGRATION ENDTIME=1 h, MAXDT=1 s, MINDT=5 s\n", "mindt_above_maxdt"),
        ("INTEGRATION ENDTIME=1 h, MAXDT=1 min, DTSTART=2 min\n", "dtstart_above_maxdt"),
        (GOOD_INTEGRATION + "TREND DTPLOT=2 h\n", "dtplot_above_endtime"),
        (GOOD_INTEGRATION + "PROFILE DTPLOT=7200 s\n", "dtplot_above_endtime"),
        (GOOD_INTEGRATION + GOOD_PIPE.replace("DIAMETER=0.2 m", "DIAMETER=0 m"), "diameter_not_positive"),
        (GOOD_INTEGRATION + GOOD_PIPE.replace("(50, 50)", "(50, -1)"), "segment_not_positive"),
        (GOOD_INTEGRATION + GOOD_PIPE.replace("NSEGMENT=2", "NSEGMENT=3"), "nsegment_mismatch"),
        (GOOD_INTEGRATION + GOOD_PIPE.replace("ROUGHNESS=0.00005 m", "ROUGHNESS=0.02 m"), "roughness_vs_diameter"),
    ],
)
def test_each_rule_has_a_case_that_triggers_it(text: str, rule: str) -> None:
    assert _rules(text) == [rule]


def test_a_unit_the_checks_cannot_read_gives_no_warning() -> None:
    assert _rules(GOOD_INTEGRATION + GOOD_PIPE.replace("DIAMETER=0.2 m", "DIAMETER=-1 furlong")) == []
    assert _rules("INTEGRATION ENDTIME=1 h, MAXDT=1 parsec, MINDT=5 s\n") == []


def test_comments_and_continuations_are_read_like_olga_reads_them() -> None:
    text = GOOD_INTEGRATION + "! PIPE DIAMETER=-1 m\nPIPE LABEL=P2, LSEGMENT=(10, 10) m, \\\n  NSEGMENT=2, DIAMETER=-0.1 m\n"
    assert _rules(text) == ["diameter_not_positive"]


def test_the_checks_never_change_the_file(tmp_path: Path) -> None:
    case = tmp_path / "case.genkey"
    case.write_bytes((FIXTURES / "intentionally_broken.genkey").read_bytes())
    before = case.read_bytes()
    case_lint.lint_case(case)
    assert case.read_bytes() == before


def test_coverage_splits_every_key_into_table_sweep_or_fixed(tmp_path: Path) -> None:
    case = tmp_path / "case.genkey"
    case.write_text(GOOD_INTEGRATION + GOOD_PIPE + GOOD_PIPE.replace("P1", "P2"), encoding="utf-8")
    # Table rows carry the field they change (case_edit_table._row).
    rows = [{"op": {"op": "set_integration"}, "field": "end_time_s"}, {"op": {"op": "set_pipe_roughness"}, "field": "roughness_m"}]
    coverage = case_lint.keyword_coverage(case, rows)
    assert coverage["table"] == ["INTEGRATION.ENDTIME", "PIPE.ROUGHNESS"]
    assert "INTEGRATION.MAXDT" in coverage["sweep"]
    assert "PIPE.DIAMETER" in coverage["fixed"]
    assert "PIPE.ROUGHNESS" not in coverage["fixed"]
    groups = coverage["table"] + coverage["sweep"] + coverage["fixed"]
    assert len(groups) == len(set(groups))


def test_the_edit_rows_route_carries_the_coverage(ws: Path) -> None:
    case = ws / install_example("valve-shut-in")["case_rel"]
    response = TestClient(app).get("/api/case-edit/rows", params={"rel": case.name})
    assert response.status_code == 200, response.text
    coverage = response.json()["coverage"]
    assert "VALVE.OPENING" in coverage["table"]
    assert "INTEGRATION.ENDTIME" in coverage["table"]
    assert coverage["sweep"] and coverage["fixed"]


def test_the_run_preview_carries_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from olga_companion import runner
    from olga_runtime_test_support import _installed_release

    case = tmp_path / "case" / "case.genkey"
    case.parent.mkdir()
    case.write_text("CASE LABEL=case\nINTEGRATION ENDTIME=10 s\nTREND DTPLOT=60 s\nENDCASE\n", encoding="utf-8")
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", opi=False)
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe")])
    monkeypatch.setattr(runner, "_validate_case", lambda _path: {"valid": True, "command": {}})
    monkeypatch.setattr(runner, "ensure_broker", lambda: SimpleNamespace(to_dict=lambda: {"protocol": "test", "sha256": "b" * 64}))
    preview = runner.preview_run(str(case))
    assert [w["rule"] for w in preview["lint"]] == ["dtplot_above_endtime"]
