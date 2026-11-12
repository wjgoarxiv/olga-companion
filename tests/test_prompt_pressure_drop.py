"""After a run the model reads both trend ends and states the pressure drop.

On 2026-11-10 a five-metre air-water run recorded PT at the first and the last
section, but the model read only the inlet and never gave the drop the user asked about.
"""

from __future__ import annotations

from olga_companion.agent.runtime import SYSTEM_PROMPT

FLAT = " ".join(SYSTEM_PROMPT.split()).lower()


def test_prompt_reads_both_ends_and_subtracts() -> None:
    assert "read pt at the first and the last trend position" in FLAT
    assert "state the pressure drop as their difference" in FLAT
