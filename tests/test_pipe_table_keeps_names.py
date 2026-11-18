"""The case keeps the engineer's flowpath and node names as OLGA labels.

Live PVT 2026-11-16 (hr01): WELL_A became FP_001, WA became SRC_001 and SEP became
SNK_001, so the run's results no longer spoke the engineer's names. A table name is
kept (upper-cased, other characters as _) when it is a valid label, unique, and does
not look like a generated one; otherwise the generated label stays.
"""

from __future__ import annotations

from pathlib import Path

from olga_companion.pipe_table import read_table
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

_HEADER = "Line,From,To,Length (m),Elevation (m),Diameter (mm),Roughness (mm),Node,Node kind,Pressure (bar),Temperature (C),Gas fraction,Water fraction\n"
_BOUNDARIES = (
    ",,,,,,,{a},source,12,40,1,0.9\n"
    ",,,,,,,{b},source,11,40,1,0.9\n"
    ",,,,,,,{s},sink,8,30,1,0.9\n"
)


def _build(tmp_path: Path, a: str = "WA", b: str = "WB", s: str = "SEP", lines=("WELL_A", "WELL_B", "TRUNK"), j: str = "J1"):
    text = _HEADER + (
        f"{lines[0]},{a},{j},500,-5,150,0.045,,,,,,\n"
        f"{lines[1]},{b},{j},600,10,150,0.045,,,,,,\n"
        f"{lines[2]},{j},{s},1500,25,250,0.045,,,,,,\n"
    ) + _BOUNDARIES.format(a=a, b=b, s=s)
    path = tmp_path / "pipes.csv"
    path.write_text(text, encoding="utf-8")
    options = ImportOptions(pvt_reference="fluid.tab", fluid_label="F", thermal={"model": "adiabatic"}, end_time_s=60.0)
    result = build_case_spec(read_table(path), options)
    assert result.spec is not None, result.issues
    return result


def test_table_names_become_labels(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result.label_map["flowpaths"] == {"WELL_A": "WELL_A", "WELL_B": "WELL_B", "TRUNK": "TRUNK"}
    assert result.label_map["nodes"] == {"WA": "WA", "J1": "J1", "WB": "WB", "SEP": "SEP"}
    assert {fp["label"] for fp in result.spec["flowpaths"]} == {"WELL_A", "WELL_B", "TRUNK"}
    assert {node["label"] for node in result.spec["nodes"]} == {"WA", "WB", "J1", "SEP"}


def test_names_are_cleaned_into_labels(tmp_path: Path) -> None:
    result = _build(tmp_path, a="wa-1", lines=("Well A", "WELL_B", "TRUNK"))
    assert result.label_map["flowpaths"]["Well A"] == "WELL_A"
    assert result.label_map["nodes"]["wa-1"] == "WA_1"


def test_a_clash_or_a_generated_looking_name_keeps_the_generated_label(tmp_path: Path) -> None:
    result = _build(tmp_path, a="TRUNK", b="FP_001", lines=("WELL_A", "WELL_B", "TRUNK"))
    labels = [*result.label_map["flowpaths"].values(), *result.label_map["nodes"].values()]
    assert len(labels) == len(set(labels))
    assert result.label_map["nodes"]["FP_001"].startswith("SRC_")
    assert result.label_map["flowpaths"]["TRUNK"] == "TRUNK"
    assert result.label_map["nodes"]["TRUNK"].startswith("SRC_")


def test_a_name_that_cannot_be_a_label_keeps_the_generated_label(tmp_path: Path) -> None:
    result = _build(tmp_path, a="1번정", s="분리기")
    assert result.label_map["nodes"]["1번정"].startswith("SRC_")
    assert result.label_map["nodes"]["분리기"].startswith("SNK_")


def test_a_reserved_label_keeps_the_generated_label(tmp_path: Path) -> None:
    # OLGA 2022.1.0 crashed on a junction labelled BOTTOM (RESERVED_LABELS).
    result = _build(tmp_path, j="bottom")
    assert result.label_map["nodes"]["bottom"].startswith("J_")


# Review 2026-11-16: POS_<fp>_1 of flowpath A is POS_<fp> of flowpath A_1.
def test_names_whose_positions_would_collide_keep_one_generated_label(tmp_path: Path) -> None:
    result = _build(tmp_path, lines=("A", "A_1", "TRUNK"))
    labels = result.label_map["flowpaths"]
    assert labels["A"] == "A" and labels["A_1"].startswith("FP_")


def test_a_name_that_loses_letters_keeps_the_generated_label(tmp_path: Path) -> None:
    # "주배관 A" would read as just "A".
    result = _build(tmp_path, lines=("주배관 A", "WELL_B", "TRUNK"))
    assert result.label_map["flowpaths"]["주배관 A"].startswith("FP_")
