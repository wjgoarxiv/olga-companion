"""evaluate accepts the run:<id>/<file> result ids the other result tools hand out.

Hyper-real round 3 (2026-11-11): after a finished riser run the model called evaluate with
{"kind": "slugging", "params": {"ppl": "run:b939301e3295/case.ppl", ...}} and got
"File not found: <app data>\\run:b939301e3295\\case.ppl"; results_series had read the same
run through the same id moments before.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import olga_companion.workspace as workspace
from olga_companion.evaluation import evaluate

FIXTURES = Path(__file__).parent / "fixtures" / "results"
EVAL_PPL = FIXTURES / "eval_case.ppl"
TPL = FIXTURES / "fixture.tpl"


@pytest.fixture
def run_ids(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []
    files = {"run:abc123/case.ppl": EVAL_PPL, "run:abc123/case.tpl": TPL}

    def resolve(identifier: str) -> Path:
        asked.append(identifier)
        return files[identifier]

    monkeypatch.setattr(workspace, "resolve_result", resolve)
    return asked


def test_slugging_reads_a_run_ppl_id(run_ids: list[str]) -> None:
    result = evaluate(
        [{"kind": "slugging", "params": {"ppl": "run:abc123/case.ppl", "branch": "Pipeline", "max_slug_count": 10}}]
    )
    assert result["judgements"][0]["verdict"] == "PASS"
    assert run_ids == ["run:abc123/case.ppl"]


def test_wax_hydrate_reads_a_run_tpl_id(run_ids: list[str]) -> None:
    result = evaluate(
        [{"kind": "wax_hydrate", "params": {"file": "run:abc123/case.tpl", "branch": "PIPELINE", "hydrate_temp": 18, "wax_temp": 25}}]
    )
    assert {j["criterion"] for j in result["judgements"]} == {"hydrate_risk", "wax_risk"}
    assert run_ids == ["run:abc123/case.tpl"]
