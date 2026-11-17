"""The pipe-table import says what OLGA's gas and water fractions mean.

Live PVT 2026-11-16 (hr01): the assistant noted that GASFRACTION is gas/(gas+oil), so an
air-water source is 1.0, and still imported 0.1. The system prompt explains it only when
no table is involved; the import tool now says it where the values are given.
"""

from __future__ import annotations

from olga_companion.agent import tools


def test_the_import_description_defines_both_fractions() -> None:
    description = tools.TOOLS["pipe_table_import"].description
    assert "gas_fraction = gas mass/(gas+oil), so 1 with no oil" in description
    assert "water_fraction = water mass/all" in description
