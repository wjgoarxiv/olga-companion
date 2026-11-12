"""The documented template is the small fixture and imports cleanly."""

from __future__ import annotations

from pathlib import Path

from olga_companion.pipe_table import read_table
from olga_companion.pipe_table_import import ImportOptions, build_case_spec

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "examples" / "pipe_table_template.csv"


def test_template_matches_the_small_fixture() -> None:
    fixture = ROOT / "tests" / "fixtures" / "pipe_tables" / "small_branch.csv"
    assert TEMPLATE.read_text(encoding="utf-8") == fixture.read_text(encoding="utf-8")


def test_template_imports_without_issues() -> None:
    options = ImportOptions(
        pvt_reference="fluid.tab", fluid_label="TEST_FLUID", thermal={"model": "adiabatic"}, end_time_s=600.0,
    )
    result = build_case_spec(read_table(TEMPLATE), options)
    assert result.issues == () and result.spec is not None


def test_the_doc_states_the_limits_the_code_enforces() -> None:
    from olga_companion.case_spec import V3_MAX_TOTAL_SECTIONS, V3_MAX_VALVES

    text = (ROOT / "docs" / "PIPE_TABLE.md").read_text(encoding="utf-8")
    assert f"{V3_MAX_VALVES} valves" in text
    assert f"{V3_MAX_TOTAL_SECTIONS:,} sections" in text
