from __future__ import annotations

import math
from pathlib import Path
from typing import TypeAlias

import pytest
from fastapi.testclient import TestClient

from olga_companion import results as results_module
from olga_companion import sidecar as sidecar_module
from olga_companion.sidecar import app

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


def test_series_view_filters_and_converts_once_before_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    class Command:
        exit_code = 0
        stdout = (
            '{"time":[0,60,120,180],"values":[100000,200000,300000,400000],'
            '"unit":"PA","time_unit":"s","position":"B"}'
        )

    monkeypatch.setattr(results_module, "resolve_result", lambda _path: Path("/tmp/source.tpl"))
    monkeypatch.setattr(results_module, "file_sha256", lambda _path: "stable")
    monkeypatch.setattr(results_module, "run_tool", lambda *_args, **_kwargs: Command())

    result = results_module.variable_series(
        "source.tpl",
        "PT",
        position="B",
        value_unit="bar",
        time_unit="min",
        range_spec={"mode": "tail", "fraction": 0.5},
    )

    assert result["time"] == pytest.approx([2.0, 3.0])
    assert result["values"] == pytest.approx([3.0, 4.0])
    assert result["unit"] == "bar"
    assert result["time_unit"] == "min"
    assert result["analysis"]["samples"] == 2
    assert result["analysis"]["start_time"] == 2.0
    assert result["analysis"]["minimum"] == 3.0
    assert result["view"]["range"] == {
        "mode": "tail",
        "fraction": 0.5,
        "start": 2.0,
        "end": 3.0,
        "samples": 2,
    }
    assert result["view"]["value_conversion"]["status"] == "converted"
    assert result["view"]["time_conversion"]["status"] == "converted"


def test_exact_bounds_and_one_sample_constant_series_are_safe() -> None:
    from olga_companion.results import apply_series_view

    result = apply_series_view(
        [0.0, 10.0, 20.0],
        [7.0, 7.0, 7.0],
        source_unit="Pa",
        source_time_unit="s",
        value_unit="kPa",
        time_unit="s",
        range_spec={"mode": "bounds", "start": 10.0, "end": 10.0},
    )

    assert result["time"] == [10.0]
    assert result["values"] == pytest.approx([0.007])
    assert result["analysis"]["samples"] == 1
    assert result["analysis"]["direction"] == "stable"


@pytest.mark.parametrize("quantity_kind, expected", [("point", 50.0), ("delta", 18.0)])
def test_series_view_exposes_temperature_quantity_kind(
    quantity_kind: str, expected: float
) -> None:
    from olga_companion.results import apply_series_view

    result = apply_series_view(
        [0.0],
        [10.0],
        source_unit="C",
        source_time_unit="s",
        value_unit="F",
        quantity_kind=quantity_kind,
    )

    assert result["values"] == pytest.approx([expected])
    assert result["view"]["value_conversion"]["quantity_kind"] == quantity_kind


def test_series_view_rejects_unknown_quantity_kind() -> None:
    from olga_companion.results import apply_series_view

    with pytest.raises(ValueError, match="quantity_kind"):
        apply_series_view(
            [0.0],
            [10.0],
            source_unit="C",
            source_time_unit="s",
            value_unit="F",
            quantity_kind="mystery",
        )


def test_series_view_rejects_decreasing_time_without_sorting() -> None:
    from olga_companion.results import apply_series_view

    with pytest.raises(ValueError, match="non-decreasing"):
        apply_series_view(
            [0.0, 2.0, 1.0],
            [1.0, 2.0, 3.0],
            source_unit="Pa",
            source_time_unit="s",
        )


def test_series_view_allows_duplicate_non_decreasing_timestamps() -> None:
    from olga_companion.results import apply_series_view

    result = apply_series_view(
        [0.0, 1.0, 1.0, 2.0],
        [1.0, 2.0, 3.0, 4.0],
        source_unit="Pa",
        source_time_unit="s",
        range_spec={"mode": "bounds", "start": 1.0, "end": 1.0},
    )

    assert result["time"] == [1.0, 1.0]
    assert result["values"] == [2.0, 3.0]
    assert result["analysis"]["samples"] == 2


@pytest.mark.parametrize(
    "range_spec, message",
    [
        ({"mode": "tail", "fraction": 0.0}, "fraction"),
        ({"mode": "tail", "fraction": math.nan}, "finite"),
        ({"mode": "bounds", "start": 2.0, "end": 1.0}, "reversed"),
        ({"mode": "bounds", "start": math.inf, "end": math.inf}, "finite"),
        ({"mode": "bounds", "start": 4.0, "end": 5.0}, "no samples"),
        ({"mode": "mystery"}, "mode"),
    ],
)
def test_series_view_rejects_malformed_or_empty_ranges(range_spec: dict, message: str) -> None:
    from olga_companion.results import apply_series_view

    with pytest.raises(ValueError, match=message):
        apply_series_view(
            [0.0, 1.0, 2.0],
            [1.0, 2.0, 3.0],
            source_unit="Pa",
            source_time_unit="s",
            range_spec=range_spec,
        )


def test_series_route_accepts_stable_view_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_series(path: str, variable: str, position: str | None = None, **view: JsonValue) -> JsonObject:
        captured.update({"path": path, "variable": variable, "position": position, **view})
        return {
            "path": path,
            "variable": variable,
            "position": position,
            "unit": "bar",
            "time_unit": "min",
            "time": [1.0],
            "values": [2.0],
            "analysis": {"samples": 1},
            "view": {},
        }

    monkeypatch.setattr(sidecar_module, "variable_series", fake_series)

    response = TestClient(app).post(
        "/api/results/series",
        json={
            "rel": "fixture.tpl",
            "variable": "PT",
            "position": "B",
            "value_unit": "bar",
            "time_unit": "min",
            "quantity_kind": "delta",
            "range": {"mode": "bounds", "start": 1.0, "end": 1.0},
        },
    )

    assert response.status_code == 200, response.text
    assert captured == {
        "path": "fixture.tpl",
        "variable": "PT",
        "position": "B",
        "value_unit": "bar",
        "time_unit": "min",
        "quantity_kind": "delta",
        "range_spec": {"mode": "bounds", "start": 1.0, "end": 1.0},
    }


def test_series_route_rejects_unknown_range_fields() -> None:
    response = TestClient(app).post(
        "/api/results/series",
        json={
            "rel": "fixture.tpl",
            "variable": "PT",
            "range": {"mode": "full", "unexpected": 1},
        },
    )

    assert response.status_code == 422


def test_series_route_rejects_unknown_quantity_kind() -> None:
    response = TestClient(app).post(
        "/api/results/series",
        json={"rel": "fixture.tpl", "variable": "TM", "quantity_kind": "mystery"},
    )

    assert response.status_code == 422
