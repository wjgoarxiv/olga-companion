"""A pipe table case gets a field-sized mesh unless the user asks for another.

Live PVT 2026-11-16 (hr01): a 3.9 km gathering network imported with the old 1 m
default became 3,903 sections. OLGA aborted it at 11 s ("temperature above table
values", 80 C on an adiabatic 40 C line). The same case meshed at 50 m ran the full
hour to a normal stop in 5 s.
"""

from __future__ import annotations

from pathlib import Path

from olga_companion.pipe_table import read_table
from olga_companion.pipe_table_import import DEFAULT_MAX_SECTION_M, ImportOptions, build_case_spec

_GATHERING = (
    "Line,From,To,Length (m),Elevation (m),Diameter (mm),Roughness (mm),Node,Node kind,Pressure (bar),Temperature (C),Gas fraction,Water fraction\n"
    "WELL_A,WA,J1,500,-5,150,0.045,,,,,,\n"
    "WELL_A,WA,J1,300,-7,150,0.045,,,,,,\n"
    "WELL_B,WB,J1,600,10,150,0.045,,,,,,\n"
    "TRUNK,J1,SEP,1500,25,250,0.045,,,,,,\n"
    "TRUNK,J1,SEP,700,-8,250,0.045,,,,,,\n"
    "TRUNK,J1,SEP,300,0,250,0.045,,,,,,\n"
    ",,,,,,,WA,source,12,40,1,0.9\n"
    ",,,,,,,WB,source,11,40,1,0.9\n"
    ",,,,,,,SEP,sink,8,30,1,0.9\n"
)


def _options(**override) -> ImportOptions:
    return ImportOptions(pvt_reference="fluid.tab", fluid_label="F", thermal={"model": "adiabatic"},
                         end_time_s=3600.0, **override)


def test_the_default_section_is_fifty_metres() -> None:
    assert DEFAULT_MAX_SECTION_M == 50.0
    assert _options().max_section_m == DEFAULT_MAX_SECTION_M


def test_a_field_network_gets_tens_of_sections_not_thousands(tmp_path: Path) -> None:
    path = tmp_path / "gathering.csv"
    path.write_text(_GATHERING, encoding="utf-8")
    result = build_case_spec(read_table(path), _options())
    assert result.spec is not None, result.issues
    assert 40 <= result.summary["sections"] <= 200
    assert result.summary["longest_section_m"] <= DEFAULT_MAX_SECTION_M


def test_the_chat_tool_uses_the_same_default() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "olga_companion" / "agent" / "pipe_table_tools.py").read_text(encoding="utf-8")
    assert 'segmentation.get("max_section_m", DEFAULT_MAX_SECTION_M)' in source


# Live PVT 2026-11-16 (hr01): the case wrote only HOL, PT and TM, so "how much reaches
# the separator?" had no answer. Mass flow (GT) and liquid flow (QLT) are written too.
def test_flow_is_written_by_default(tmp_path: Path) -> None:
    from olga_companion.case_compiler import compile_case_spec

    path = tmp_path / "gathering.csv"
    path.write_text(_GATHERING, encoding="utf-8")
    result = build_case_spec(read_table(path), _options())
    assert {"GT", "QLT"} <= set(result.spec["outputs"])
    text = compile_case_spec(result.spec).text
    trends = [line for line in text.splitlines() if "TRENDDATA POSITION" in line]
    assert trends and all("GT" in line and "QLT" in line for line in trends)
