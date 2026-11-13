"""run_preview says its timeout is wall-clock time, not the simulated end time.

Hyper-real round 8 (2026-11-11): for a 3-hour simulated end time the model told a
novice "The wall-clock limit defaults to 1 hour. This end time is 3 hours, so it may
need longer" and asked for a limit before the run. The case finishes in minutes; the
timeout_s argument had no description at all.
"""
from __future__ import annotations

from olga_companion.agent import tools


def test_the_run_timeout_is_described_as_wall_clock_not_simulated_time() -> None:
    description = tools.TOOLS["run_preview"].description.lower()
    assert "wall-clock" in description
    assert "not the simulated end time" in description
