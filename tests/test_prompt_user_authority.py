"""The prompt makes a user's stated value win over a disagreeing reference, at once.

On 2026-11-10 a novice quoted OLGA's own GASFRACTION definition (a mass fraction) and gave
new values; the model kept the glossary's volume reading until the user insisted twice.
"""

from __future__ import annotations

from olga_companion.agent.runtime import SYSTEM_PROMPT

FLAT = " ".join(SYSTEM_PROMPT.split())


def test_prompt_says_boundary_fractions_are_mass_fractions() -> None:
    lowered = FLAT.lower()
    assert "gas_fraction and total_water_fraction are olga mass fractions" in lowered
    assert "never volume fractions" in lowered


def test_a_user_volume_basis_is_converted_not_passed_through() -> None:
    lowered = FLAT.lower()
    assert "a fraction the user gives on a volume basis is converted to mass" in lowered
    assert "never submit a computed fraction the user has not accepted" in lowered


def test_prompt_applies_a_user_correction_in_the_next_tool_call() -> None:
    lowered = FLAT.lower()
    assert "a value or definition the user states" in lowered
    assert "is used at once in the next tool call" in lowered
    assert "still use the user's value" in lowered
