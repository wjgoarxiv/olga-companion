"""A call held back behind an approval says to make it again once that call has a result.

Hyper-real round 8 (English UI, 2026-11-11): the model sent fluids_starter_tab,
case_spec_validate and case_spec_compile in one reply. The last two were answered
"Not run: an earlier call needs approval." After the approval the continuation replays
that sentence, still in the present tense, and the model told the user the copy was
"waiting for your approval" and stopped without validating the case.
"""
from __future__ import annotations

import pytest

from olga_companion.agent import runtime


@pytest.mark.parametrize("locale", ["en", "ko"])
def test_the_not_run_answer_holds_after_the_approval(locale: str) -> None:
    message = runtime._not_run_message(locale)
    assert "needs approval" not in message
    assert "기다리고 있습니다" not in message
    if locale == "en":
        assert "again" in message
    else:
        assert "다시" in message
