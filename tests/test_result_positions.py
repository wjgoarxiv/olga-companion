from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import results as results_module
from olga_companion.sidecar import app


@pytest.mark.parametrize(
    "returned",
    [
        "SECTION",
        "Br",
        "PIPE",
        "NR",
        "PIPE-1",
        "1",
        "LINE",
        "PIPELINE-extra",
        "..",
        "../PIPELINE",
        "PIPELINE/..",
        "-PIPELINE",
    ],
)
def test_structured_position_equivalence_accepts_only_complete_branch_value(returned: str) -> None:
    from olga_companion.results import _positions_equivalent

    selector = "SECTION - Br - PIPELINE - PIPE - PIPE-1 - NR - 1"
    assert _positions_equivalent(selector, "pipeline") is True
    assert _positions_equivalent(selector, returned) is False


@pytest.mark.parametrize(
    "selector, returned",
    [
        ("SECTION - PIPE - PIPELINE - NR - 1", "PIPELINE"),
        ("SECTION - Br", "Br"),
        ("SECTION - Br - ", ""),
        ("SECTION - Br - PIPELINE - PIPE", "PIPELINE"),
        ("SECTION - Br - PIPELINE - Br - OTHER", "PIPELINE"),
        ("SECTION - Br - PIPELINE - Br - OTHER", "OTHER"),
        ("SECTION - Br - .. - PIPE - PIPE-1", ".."),
        ("SECTION - Br - -PIPELINE - PIPE - PIPE-1", "-PIPELINE"),
    ],
)
def test_structured_position_equivalence_rejects_missing_duplicate_or_malformed_br_pairs(
    selector: str, returned: str
) -> None:
    from olga_companion.results import _positions_equivalent

    assert _positions_equivalent(selector, returned) is False


def test_simple_position_equivalence_remains_exact() -> None:
    from olga_companion.results import _positions_equivalent

    assert _positions_equivalent("INLET", "inlet") is True
    assert _positions_equivalent("INLET", "IN") is False


@pytest.mark.parametrize("returned, accepted", [("PIPELINE", True), ("OUTLET", False)])
def test_variable_series_accepts_only_equivalent_structured_parser_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returned: str,
    accepted: bool,
) -> None:
    source = tmp_path / "source.tpl"
    source.write_bytes(b"structured position source")
    selector = "SECTION - Br - PIPELINE - PIPE - PIPE-1 - NR - 1"

    class Command:
        exit_code = 0
        stdout = (
            '{"time":[0,1],"values":[10,11],"unit":"C","time_unit":"s",'
            f'"position":"{returned}"}}'
        )

    monkeypatch.setattr(results_module, "resolve_result", lambda _path: source)
    monkeypatch.setattr(results_module, "run_tool", lambda *_args, **_kwargs: Command())

    if accepted:
        result = results_module.variable_series(str(source), "TM", selector)
        assert result["position"] == returned
    else:
        with pytest.raises(ValueError, match="expected"):
            results_module.variable_series(str(source), "TM", selector)


def test_fixture_load_position_round_trips_through_series_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "results"
    fixture = fixture_root / "fixture.tpl"
    if not fixture.exists():
        pytest.skip("result fixture unavailable")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(fixture_root))
    loaded = results_module.load_result(str(fixture))
    selected = next(
        entry
        for entry in loaded["variables"]
        if entry["variable"] == "TM" and entry["position"].startswith("SECTION - ")
    )

    response = TestClient(app).post(
        "/api/results/series",
        json={
            "rel": fixture.name,
            "variable": selected["variable"],
            "position": selected["position"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["position"].casefold() in {
        component.casefold() for component in selected["position"].split(" - ")
    }
