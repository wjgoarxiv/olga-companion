"""Pressure-drop criterion: end-of-run + max-over-time drop with full citations."""
from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import evaluation as evaluation_module
from olga_companion.evaluation import CITATION_FIELDS, evaluate

FIXTURES = Path(__file__).parent / "fixtures" / "results"
TPL = FIXTURES / "fixture.tpl"

PARAMS = {
    "tpl": str(TPL),
    "inlet_position": "POSITION - INLET",
    "outlet_position": "PIPELINE",
    "max_drop": 3.0e6,
    "unit": "Pa",
}


@pytest.fixture()
def _fixture_tpl(monkeypatch: pytest.MonkeyPatch) -> Path:
    from olga_companion import results as results_module

    monkeypatch.setattr(results_module, "resolve_result", lambda _value: TPL)
    return TPL


def test_pressure_drop_computes_end_and_max_with_citations(_fixture_tpl: Path) -> None:
    result = evaluate([{"kind": "pressure_drop", "params": dict(PARAMS)}])
    (judgement,) = result["judgements"]
    assert judgement["criterion"] == "pressure_drop"
    assert judgement["verdict"] == "PASS"
    assert judgement["measured"]["drop_end"] == pytest.approx(2.06e6)
    assert judgement["measured"]["drop_max"] == pytest.approx(2.1e6)
    assert judgement["measured"]["drop_unit"] == "Pa"
    assert judgement["threshold"] == {"max_drop": 3.0e6, "unit": "Pa"}
    assert judgement["variables"] == ["PT"]
    assert judgement["source_file"] == str(TPL)
    assert judgement["mapping"]["inlet_position"] == "INLET"
    assert judgement["mapping"]["outlet_position"] == "PIPELINE"
    missing = [field for field in CITATION_FIELDS if judgement.get(field) is None]
    assert not missing


def test_pressure_drop_fails_above_limit(_fixture_tpl: Path) -> None:
    result = evaluate(
        [{"kind": "pressure_drop", "params": {**PARAMS, "max_drop": 2.0e6}}]
    )
    assert result["judgements"][0]["verdict"] == "FAIL"


def test_pressure_drop_missing_threshold_is_input_required(_fixture_tpl: Path) -> None:
    params = dict(PARAMS)
    del params["max_drop"]
    result = evaluate([{"kind": "pressure_drop", "params": params}])
    assert result["judgements"] == []
    (pending,) = result["pending"]
    assert pending["criterion"] == "pressure_drop"
    assert pending["status"] == "input_required"
    assert "max_drop" in pending["missing"]
    assert "verdict" not in pending


def test_pressure_drop_rejects_a_shifted_time_grid(_fixture_tpl: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from olga_companion import results as results_module
    from olga_companion.genkey_static import OlgaInputError

    def series(_path: str, _variable: str, position: str | None = None, **_kwargs: object) -> dict:
        shifted = "INLET" not in (position or "")
        return {
            "time": [0.0, 2.0] if shifted else [0.0, 1.0],
            "values": [1.0, 0.0] if shifted else [3.0, 1.0],
            "path": str(TPL),
            "position": "PIPELINE" if shifted else "INLET",
            "unit": "Pa",
            "time_unit": "s",
        }

    monkeypatch.setattr(results_module, "variable_series", series)

    with pytest.raises(OlgaInputError, match="time grids"):
        evaluate([{"kind": "pressure_drop", "params": dict(PARAMS)}])


def test_pressure_drop_rejects_non_finite_values_and_threshold(
    _fixture_tpl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import results as results_module
    from olga_companion.genkey_static import OlgaInputError

    def series(_path: str, _variable: str, position: str | None = None, **_kwargs: object) -> dict:
        return {
            "time": [0.0, 1.0],
            "values": [float("nan"), 1.0],
            "path": str(TPL),
            "position": position,
            "unit": "Pa",
            "time_unit": "s",
        }

    monkeypatch.setattr(results_module, "variable_series", series)

    with pytest.raises(OlgaInputError, match="non-finite"):
        evaluate([{"kind": "pressure_drop", "params": dict(PARAMS)}])
    monkeypatch.setattr(
        results_module,
        "variable_series",
        lambda *_args, **_kwargs: {
            "time": [0.0, 1.0],
            "values": [2.0, 1.0],
            "path": str(TPL),
            "position": "INLET",
            "unit": "Pa",
            "time_unit": "s",
        },
    )
    with pytest.raises(OlgaInputError, match="max_drop"):
        evaluate([{"kind": "pressure_drop", "params": {**PARAMS, "max_drop": float("inf")}}])


def test_pressure_drop_hashes_the_source_before_reading(
    _fixture_tpl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import results as results_module

    order: list[str] = []
    real_hash = evaluation_module.file_sha256
    real_series = results_module.variable_series

    def hashed(path: Path) -> str:
        order.append("hash")
        return real_hash(path)

    def series(*args: object, **kwargs: object) -> dict:
        order.append("read")
        return real_series(*args, **kwargs)

    monkeypatch.setattr(evaluation_module, "file_sha256", hashed)
    monkeypatch.setattr(results_module, "variable_series", series)

    evaluate([{"kind": "pressure_drop", "params": dict(PARAMS)}])

    assert order[0] == "hash"
    assert "read" in order
