from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import olga_companion.evaluation as evaluation_module
from olga_companion.evaluation import CITATION_FIELDS, evaluate, evaluation_toolkit_status
from olga_companion.genkey_static import file_sha256
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures" / "results"
EVAL_PPL = FIXTURES / "eval_case.ppl"
TPL = FIXTURES / "fixture.tpl"
SAMPLE_GENKEY = Path(__file__).parent / "fixtures" / "cases" / "simple_pipeline.genkey"

pytestmark = pytest.mark.skipif(
    not (evaluation_toolkit_status()["available"] and SAMPLE_GENKEY.exists()),
    reason="OLGA evaluation toolkit scripts or sample cases are unavailable",
)

LIQC_PARAMS = {
    "ppl": str(EVAL_PPL),
    "genkey": str(SAMPLE_GENKEY),
    "flowpath": "FLOWPATH_1",
    "pipe": "Pipe_2",
    "branch": "Pipeline",
}


def test_liqc_verdict_flips_with_threshold() -> None:
    before = file_sha256(EVAL_PPL)
    passing = evaluate([{"kind": "liqc", "params": {**LIQC_PARAMS, "max_litres": 3000}}])
    assert passing["judgements"][0]["verdict"] == "PASS"
    failing = evaluate([{"kind": "liqc", "params": {**LIQC_PARAMS, "max_litres": 2000}}])
    assert failing["judgements"][0]["verdict"] == "FAIL"
    assert file_sha256(EVAL_PPL) == before
    measured = passing["judgements"][0]["measured"]
    assert 2800 < measured["liqc_litres"] < 2860


def test_every_judgement_carries_all_citation_fields() -> None:
    result = evaluate(
        [
            {"kind": "liqc", "params": {**LIQC_PARAMS, "max_litres": 3000}},
            {"kind": "slugging", "params": {"ppl": str(EVAL_PPL), "branch": "Pipeline", "max_slug_count": 10}},
            {
                "kind": "wax_hydrate",
                "params": {"file": str(TPL), "branch": "PIPELINE", "hydrate_temp": 18, "wax_temp": 25},
            },
        ]
    )
    assert len(result["judgements"]) == 4  # liqc + slugging + hydrate + wax
    for judgement in result["judgements"]:
        for field in CITATION_FIELDS:
            assert field in judgement, f"missing citation field {field}"
            assert judgement[field] is not None
        # The evidence chain is structured tool output only; no free-text
        # narrative fields beyond the declared schema.
        assert set(judgement.keys()) <= CITATION_FIELDS | {"measured"}


def test_slugging_verdict_flips_with_threshold() -> None:
    strict = evaluate([{"kind": "slugging", "params": {"ppl": str(EVAL_PPL), "branch": "Pipeline", "max_slug_count": 0}}])
    assert strict["judgements"][0]["verdict"] == "FAIL"
    loose = evaluate([{"kind": "slugging", "params": {"ppl": str(EVAL_PPL), "branch": "Pipeline", "max_slug_count": 10}}])
    assert loose["judgements"][0]["verdict"] == "PASS"


def test_wax_hydrate_judgements_reflect_fixture_temperatures() -> None:
    result = evaluate(
        [{"kind": "wax_hydrate", "params": {"file": str(TPL), "branch": "PIPELINE", "hydrate_temp": 18, "wax_temp": 25}}]
    )
    by_criterion = {judgement["criterion"]: judgement for judgement in result["judgements"]}
    assert by_criterion["hydrate_risk"]["verdict"] == "PASS"
    assert by_criterion["wax_risk"]["verdict"] == "FAIL"


def test_unknown_criterion_and_missing_params_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown criterion kind"):
        evaluate([{"kind": "made_up", "params": {}}])
    with pytest.raises(ValueError, match="max_litres"):
        evaluate([{"kind": "liqc", "params": {**LIQC_PARAMS}}])
    with pytest.raises(ValueError, match="Invalid"):
        evaluate([{"kind": "liqc", "params": {**LIQC_PARAMS, "max_litres": 3000, "pipe": "Pipe_2; rm -rf"}}])


def test_thresholds_reject_booleans_and_strings() -> None:
    with pytest.raises(ValueError, match="numeric"):
        evaluate([{"kind": "liqc", "params": {**LIQC_PARAMS, "max_litres": True}}])
    with pytest.raises(ValueError, match="numeric"):
        evaluate([{"kind": "liqc", "params": {**LIQC_PARAMS, "max_litres": "3000"}}])


def test_citation_incomplete_judgement_maps_to_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(evaluation_module._JUDGES, "liqc", lambda params: [{"criterion": "broken"}])
    client = TestClient(app)
    response = client.post("/api/evaluate", json={"criteria": [{"kind": "liqc", "params": {}}]})
    assert response.status_code == 500
    assert "missing citation fields" in response.json()["detail"]


def test_undeclared_judgement_fields_map_to_500(monkeypatch: pytest.MonkeyPatch) -> None:
    def chatty_judge(params: dict) -> list[dict]:
        judgement = {field: "x" for field in CITATION_FIELDS}
        judgement["narrative"] = "an LLM-style free-text field"
        return [judgement]

    monkeypatch.setitem(evaluation_module._JUDGES, "liqc", chatty_judge)
    client = TestClient(app)
    response = client.post("/api/evaluate", json={"criteria": [{"kind": "liqc", "params": {}}]})
    assert response.status_code == 500
    assert "undeclared fields" in response.json()["detail"]


def test_evaluate_route() -> None:
    client = TestClient(app)

    ok = client.post(
        "/api/evaluate",
        json={"criteria": [{"kind": "liqc", "params": {**LIQC_PARAMS, "max_litres": 3000}}]},
    )
    assert ok.status_code == 200
    assert ok.json()["judgements"][0]["verdict"] == "PASS"

    bad = client.post("/api/evaluate", json={"criteria": [{"kind": "nope", "params": {}}]})
    assert bad.status_code == 400
