"""The prompt tells the model that tool-call numbers can arrive rounded to six decimals.

On 2026-11-11 (hyper-real round 1, xai grok-4.7) an accepted 1.5e-6 m roughness reached
every case_spec call as 1e-06 and a 0.9900990099009901 fraction as 0.990099; no tool-call
number in the chat history ever carried more than six decimal places. The model blamed
itself, resent the same spec five times and stalled until the user gave up the value.
"""

from __future__ import annotations

from olga_companion.agent.runtime import SYSTEM_PROMPT

FLAT = " ".join(SYSTEM_PROMPT.split()).lower()


def test_prompt_names_the_six_decimal_rounding() -> None:
    assert "tool-call numbers can arrive rounded to six decimal places" in FLAT


def test_prompt_has_the_user_accept_the_stored_value_first() -> None:
    assert "tell the user the value that will be stored and ask them to accept it" in FLAT


def test_rounding_rule_keeps_the_verbatim_user_value() -> None:
    # The verbatim-echo rule (1e-7 stays 1e-7) must not turn into a renegotiation.
    assert "still send the user's value verbatim" in FLAT
    assert "including forms such as 1e-7" in FLAT
    assert "the user's value is never replaced without that yes" in FLAT


def test_prompt_forbids_resending_for_a_rounded_echo() -> None:
    assert "it is not an input error: do not resend the call for it" in FLAT
