"""The system prompt tells the model that a valve can close on a timetable.

Hyper-real round 6 (2026-11-11, build G, xai grok-4.7): asked to close an outlet valve
over 10 s at 60 s, the model answered that the app's valve "only supports one fixed
opening" and offered a fixed opening instead. CaseSpec version 3 already takes a valve
`schedule` of time/opening points (tests/test_casespec_v3.py); the prompt only listed a
single opening.
"""
from __future__ import annotations

from olga_companion.agent import runtime


def test_the_prompt_names_the_valve_schedule_and_its_version() -> None:
    prompt = runtime.build_system_prompt()
    assert "schedule" in prompt
    assert "time_s" in prompt
    assert 'version "3"' in prompt
