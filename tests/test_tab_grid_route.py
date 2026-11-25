from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import tab_grid
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures" / "fluids"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    return TestClient(app), tmp_path


def _copy(root: Path, name: str) -> str:
    shutil.copy(FIXTURES / name, root / name)
    return name


def test_standard_table_returns_one_property_as_a_pressure_by_temperature_matrix(client) -> None:
    http, root = client
    response = http.post("/api/fluids/tab-grid", json={"path": _copy(root, "standard_three.tab")})
    assert response.status_code == 200
    body = response.json()
    assert body["format"] == "standard"
    assert body["properties"] == ["ROG", "ROHL", "ROWT", "VISWT", "HG", "SEWT"]
    assert body["column"] == "ROG"
    assert body["pressures"] == [100000.0, 10000000.0]
    assert body["temperatures"] == [5.0, 40.0]
    assert body["values"] == [[1.0, 0.9], [100.0, 95.0]]
    assert body["downsampled"] is False


def test_standard_axes_in_bar_and_kelvin_come_back_as_pa_and_celsius(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reader refuses non-PA pressure today; if it ever lets one through, the preview still emits Pa and degrees C."""

    class _Parsed:
        label, phase = "FLUID-A", "THREE"
        columns = ["PT", "TM", "ROG"]
        pressure_grid = [1.0, 100.0]
        temperature_grid = [278.15, 313.15]
        point_rows = [[1.0, 278.15, 1.0], [1.0, 313.15, 0.9], [100.0, 278.15, 100.0], [100.0, 313.15, 95.0]]
        available_properties: list[str] = []
        n_enthalpies: list[int] = []
        _pairs = {"PRESSURE": {"unit": "bar"}, "TEMPERATURE": {"unit": "K"}}

    path = tmp_path / "bar.tab"
    path.write_text("x")
    monkeypatch.setattr(tab_grid, "_parse", lambda _path: _Parsed())
    body = tab_grid.tab_grid(str(path))
    assert body["format"] == "standard"
    assert body["pressures"] == pytest.approx([100000.0, 10000000.0])
    assert body["temperatures"] == pytest.approx([5.0, 40.0])
    assert body["values"] == [[1.0, 0.9], [100.0, 95.0]]


def test_a_chosen_column_is_returned_and_an_unknown_one_is_refused(client) -> None:
    http, root = client
    name = _copy(root, "standard_three.tab")
    body = http.post("/api/fluids/tab-grid", json={"path": name, "column": "rowt"}).json()
    assert body["column"] == "ROWT"
    assert body["values"] == [[999.0, 992.0], [1001.0, 994.0]]
    refused = http.post("/api/fluids/tab-grid", json={"path": name, "column": "NOPE"})
    assert refused.status_code == 400


def test_legacy_table_names_its_properties_without_inventing_a_grid(client) -> None:
    http, root = client
    body = http.post("/api/fluids/tab-grid", json={"path": _copy(root, "fluid.tab")}).json()
    assert body["format"] == "legacy"
    assert body["values"] is None
    assert "ROG" in body["properties"]


def test_unreadable_table_is_a_clear_refusal(client) -> None:
    http, root = client
    response = http.post("/api/fluids/tab-grid", json={"path": _copy(root, "broken.tab")})
    assert response.status_code == 400


def test_large_axes_are_sampled_keeping_both_ends() -> None:
    picked = tab_grid._sample(200)
    assert len(picked) == tab_grid.MAX_AXIS
    assert picked[0] == 0 and picked[-1] == 199
    assert picked == sorted(set(picked))
    assert tab_grid._sample(3) == [0, 1, 2]


def test_envelope_carries_bubble_dew_and_critical_point_of_a_legacy_table(client) -> None:
    http, root = client
    body = http.post("/api/fluids/tab-grid", json={"path": _copy(root, "fluid.tab")}).json()
    envelope = body["envelope"]
    assert envelope["bubble"] == [[100000.0, -56.558], [1000000.0, -40.12], [7380000.0, 30.978]]
    assert envelope["dew"][0] == [100000.0, -78.464]
    assert envelope["critical"] == {"p_pa": 7380000.0, "t_c": 30.978}


def test_envelope_is_empty_when_the_table_has_temperatures_but_no_pressures(client) -> None:
    http, root = client
    body = http.post("/api/fluids/tab-grid", json={"path": _copy(root, "standard_three.tab")}).json()
    assert body["envelope"] == {"bubble": [], "dew": [], "critical": None}


def test_envelope_reads_a_critical_point_stored_as_a_one_item_list(client) -> None:
    http, root = client
    shutil.copy(Path(__file__).parent.parent / "resources" / "fluids" / "air_water.tab", root / "aw.tab")
    envelope = http.post("/api/fluids/tab-grid", json={"path": "aw.tab"}).json()["envelope"]
    assert envelope["critical"]["p_pa"] == pytest.approx(3.786e6, rel=1e-3)
    assert envelope["critical"]["t_c"] == pytest.approx(-140.62, abs=0.02)
    assert len(envelope["bubble"]) >= 20 and len(envelope["dew"]) >= 20


def test_legacy_table_lists_one_property_per_pressure_without_a_temperature_axis(client) -> None:
    http, root = client
    name = _copy(root, "fluid.tab")
    body = http.post("/api/fluids/tab-grid", json={"path": name}).json()
    assert body["format"] == "legacy" and body["values"] is None and body["temperatures"] == []
    assert body["column"] == "ROG" and body["unit"] == "KG/M3"
    assert body["pressures"] == [100000.0, 1000000.0, 10000000.0]
    assert body["points"] == [[1.95, 2.05, 2.15], [19.5, 20.5, 21.5], [195.0, 205.0, 215.0]]
    assert body["pointIndexes"] == [0, 1, 2]
    other = http.post("/api/fluids/tab-grid", json={"path": name, "column": "rol"}).json()
    assert other["column"] == "ROL" and other["points"][0] == [1180.0, 1160.0, 1140.0]
    assert http.post("/api/fluids/tab-grid", json={"path": name, "column": "NOPE"}).status_code == 400


def test_a_long_curve_is_capped_keeping_ends_and_extremes() -> None:
    n = 1000
    points = [[float(i), float((i - 500) ** 2)] for i in range(n)]
    points[321][1] = -1.0e9
    kept = tab_grid._cap_curve(points)
    assert len(kept) <= tab_grid.MAX_CURVE
    assert kept[0] == points[0] and kept[-1] == points[-1]
    assert points[321] in kept
    assert tab_grid._cap_curve(points[:5]) == points[:5]


def test_a_non_finite_envelope_number_becomes_null() -> None:
    assert tab_grid._curve([1.0, float("inf")], [float("nan"), 2.0], "PA", "C") == [[1.0, None], [None, 2.0]]
