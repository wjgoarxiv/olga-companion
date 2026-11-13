"""Large networks stay inside the compile, toolkit and viewer limits."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from olga_companion import case_compiler
from olga_companion.case_spec import V3_MAX_TOTAL_SECTIONS
from olga_companion.flowpath_details import load_flowpath_details
from olga_companion.pipe_table import read_table
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

TABLE = Path(__file__).parent / "fixtures" / "pipe_tables" / "synthetic_network.csv"


def _options(max_section_m: float) -> ImportOptions:
    return ImportOptions(
        pvt_reference="fluid.tab", fluid_label="TEST_FLUID", thermal={"model": "adiabatic"},
        end_time_s=600.0, max_section_m=max_section_m,
    )


def test_the_synthetic_network_compiles_under_a_megabyte_quickly() -> None:
    result = build_case_spec(read_table(TABLE), _options(1.0))
    start = time.perf_counter()
    compiled = case_compiler.compile_case_spec(result.spec)
    elapsed = time.perf_counter() - start

    assert compiled.validation.clean
    assert len(compiled.compiled_bytes) < case_compiler.MAX_COMPILED_BYTES
    assert elapsed < 20.0


def test_near_the_v3_section_cap_the_toolkit_check_stays_fast() -> None:
    result = build_case_spec(read_table(TABLE), _options(0.025))
    assert 8_000 <= result.summary["sections"] <= V3_MAX_TOTAL_SECTIONS
    start = time.perf_counter()
    compiled = case_compiler.compile_case_spec(result.spec)
    assert compiled.validation.clean and time.perf_counter() - start < 20.0


def test_past_the_v3_section_cap_the_import_names_the_fix() -> None:
    result = build_case_spec(read_table(TABLE), _options(0.015))
    assert result.spec is None
    assert any("max_section_m" in issue.reason for issue in result.issues)


@pytest.fixture
def compiled_case(tmp_path: Path) -> Path:
    result = build_case_spec(read_table(TABLE), _options(1.0))
    path = tmp_path / "network.genkey"
    path.write_bytes(case_compiler.compile_case_spec(result.spec).compiled_bytes)
    return path


def test_a_length_elevation_flowpath_shows_its_profile(compiled_case: Path) -> None:
    details = load_flowpath_details(compiled_case, "FP_001")

    assert details["geometry"]["status"] == "ready"
    assert details["geometry"]["source"] == "length_elevation"
    sections = details["sections"]
    assert sections[0]["start"] == {"x_m": 0.0, "y_m": 0.0, "z_m": 0.0}
    # The supply row in the table rises 1.5 m over its second pipe.
    assert sections[-1]["end"]["y_m"] == pytest.approx(1.5)
    assert sections[-1]["chainage_end_m"] == pytest.approx(17.0)
    assert details["summary"]["segment_count"] == len(sections)
