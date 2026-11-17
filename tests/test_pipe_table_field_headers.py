"""Field-style headers read without a column map.

Live PVT 2026-11-16 (hr01): the engineer's table said `ID (mm)`. It was not read as the
inner diameter, and when the assistant mapped it, the header's mm was dropped, so 150 mm
became 150 m and the import asked to "put the unit in the header" that already had it.
Korean headers (내경, 길이, 고도) and inch, ft, psi and barg units were not read at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion.pipe_table import read_table


def _rows(tmp_path: Path, text: str, **kwargs):
    path = tmp_path / "pipes.csv"
    path.write_text(text, encoding="utf-8")
    table = read_table(path, **kwargs)
    assert not table.issues, table.issues
    return table.rows


def test_id_with_a_length_unit_is_the_inner_diameter(tmp_path: Path) -> None:
    rows = _rows(tmp_path, "Line,From,To,Length (m),Elevation (m),ID (mm),Roughness (mm)\nA,S,T,10,0,150,0.045\n")
    assert rows[0]["inner_diameter_m"] == pytest.approx(0.15)
    assert rows[0]["roughness_m"] == pytest.approx(0.000045)


def test_a_bare_id_column_is_still_a_row_identifier(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text("ID,Line,From,To,Length (m),Elevation (m),Diameter (m),Roughness (m)\n7,A,S,T,10,0,0.15,0.00005\n", encoding="utf-8")
    table = read_table(path)
    assert "inner_diameter_m" in table.rows[0] and table.rows[0]["inner_diameter_m"] == pytest.approx(0.15)
    assert "ID" in table.ignored_columns


@pytest.mark.parametrize("target", ["inner_diameter_m", "inner_diameter"])
def test_a_mapped_column_keeps_its_header_unit(tmp_path: Path, target: str) -> None:
    rows = _rows(
        tmp_path, "Line,From,To,Length (m),Elevation (m),Bore (mm),Roughness (mm)\nA,S,T,10,0,150,0.045\n",
        column_map={"Bore (mm)": target},
    )
    assert rows[0]["inner_diameter_m"] == pytest.approx(0.15)


def test_korean_headers_read(tmp_path: Path) -> None:
    rows = _rows(
        tmp_path,
        "라인,시작점,끝점,길이 (m),고도차 (m),내경 (mm),조도 (mm),노드,노드 종류,압력 (bar),온도 (C),가스 분율,물 분율\n"
        "A,S,T,10,1,150,0.045,,,,,,\n"
        ",,,,,,,S,source,12,40,1,0.9\n",
    )
    pipe, node = rows
    assert (pipe["flowpath"], pipe["from_node"], pipe["to_node"]) == ("A", "S", "T")
    assert pipe["length_m"] == 10 and pipe["elevation_m"] == 1
    assert pipe["inner_diameter_m"] == pytest.approx(0.15)
    assert node["node"] == "S" and node["node_kind"] == "source"
    assert node["pressure_pa"] == pytest.approx(1_200_000)
    assert (node["gas_fraction"], node["water_fraction"]) == (1, 0.9)


def test_field_units_convert(tmp_path: Path) -> None:
    rows = _rows(
        tmp_path,
        "Line,From,To,Length (ft),Elevation (ft),ID (in),Roughness (in),Node,Node kind,Pressure (barg),Temperature (F),Gas fraction,Water fraction\n"
        "A,S,T,1000,10,6,0.0018,,,,,,\n"
        ",,,,,,,S,source,10,104,1,0\n"
        ",,,,,,,T,sink,0,104,1,0\n",
    )
    pipe, source, sink = rows
    assert pipe["length_m"] == pytest.approx(304.8)
    assert pipe["inner_diameter_m"] == pytest.approx(0.1524)
    assert source["pressure_pa"] == pytest.approx(1_101_325)
    assert sink["pressure_pa"] == pytest.approx(101_325)
    assert source["temperature_c"] == pytest.approx(40)


def test_psi_is_absolute_and_psig_is_gauge(tmp_path: Path) -> None:
    rows = _rows(
        tmp_path,
        "Node,Node kind,Pressure (psi),Temperature (C),Gas fraction,Water fraction\nS,source,100,20,1,0\n",
    )
    assert rows[0]["pressure_pa"] == pytest.approx(689_475.729, rel=1e-6)
    rows = _rows(
        tmp_path,
        "Node,Node kind,Pressure (psig),Temperature (C),Gas fraction,Water fraction\nS,source,0,20,1,0\n",
    )
    assert rows[0]["pressure_pa"] == pytest.approx(101_325)


def test_korean_headers_with_a_unit_suffix_read(tmp_path: Path) -> None:
    rows = _rows(tmp_path, "라인,시작점,끝점,길이_m,고도차_m,내경_mm,조도_mm\nA,S,T,10,1,150,0.045\n")
    assert rows[0]["length_m"] == 10 and rows[0]["inner_diameter_m"] == pytest.approx(0.15)


def test_pipe_id_with_a_length_unit_is_the_inner_diameter(tmp_path: Path) -> None:
    rows = _rows(tmp_path, "Line,From,To,Length (m),Elevation (m),Pipe ID (mm),Roughness (mm)\nA,S,T,10,0,150,0.045\n")
    assert rows[0]["inner_diameter_m"] == pytest.approx(0.15)


def test_a_mapped_header_word_that_is_not_a_unit_keeps_the_mapped_unit(tmp_path: Path) -> None:
    rows = _rows(
        tmp_path, "Line,From,To,Length (m),Elevation (m),Diameter (nominal),Roughness (mm)\nA,S,T,10,0,0.15,0.045\n",
        column_map={"Diameter (nominal)": "inner_diameter_m"},
    )
    assert rows[0]["inner_diameter_m"] == pytest.approx(0.15)


def test_water_cut_is_not_read_as_the_water_mass_fraction(tmp_path: Path) -> None:
    path = tmp_path / "pipes.csv"
    path.write_text("노드,노드 종류,압력 (bar),온도 (C),가스 분율,함수율 (%)\nS,source,12,40,1,50\n", encoding="utf-8")
    table = read_table(path)
    assert "water_fraction" not in table.rows[0]
