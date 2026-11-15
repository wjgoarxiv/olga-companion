"""The system prompt says where each output variable is written.

Hyper-real round 8 (2026-11-11): asked how much liquid sits in the climbing part of a
line, the model proposed LIQC "so the climb can be totaled on its own pipe". The compiler
writes LIQC only as one whole-line trend (case_compiler._OUTPUT_CONTEXTS), so after the
run the question could not be answered and needed a second run with HOL.
"""
from __future__ import annotations

from olga_companion.agent import runtime
from olga_companion.case_compiler import _OUTPUT_CONTEXTS


def test_liqc_is_named_as_a_whole_line_total_and_hol_as_the_profile() -> None:
    prompt = " ".join(runtime.build_system_prompt().split())
    assert "LIQC is the liquid volume of the whole line" in prompt
    assert "use HOL" in prompt
    assert "profile" not in _OUTPUT_CONTEXTS["LIQC"]
    assert "profile" in _OUTPUT_CONTEXTS["HOL"]
