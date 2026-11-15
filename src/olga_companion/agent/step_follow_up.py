"""Detect a turn that ends by announcing its own next tool step without calling it.

Some providers end a turn on "같은 값으로 케이스 정의를 검사합니다." and stop, although the
prompt forbids it. The runtime then asks the model once to make that call.
"""

from __future__ import annotations

_WAITS_ON_USER = ("?", "？", "주시면", "주세요", "once you confirm", "once you reply", "let me know")
# Only the forms seen ending stalled turns; descriptive lines such as
# "이 도구는 케이스를 실행합니다." must not cost an extra provider call.
_STEP_VERBS = (
    "검사합니다", "검사하겠습니다", "검증하겠습니다", "넣겠습니다", "요청합니다",
    "진행합니다", "진행하겠습니다",
)
_EN_STEPS = ("i'll validate", "i will validate")
# A reply that confirms the user's go-ahead ("수락하신 대로 … 넣습니다.") before any tool call
# has acted on nothing yet. "적으신 값은 …" is the echo of the user's own numbers.
_ACKNOWLEDGES_GO_AHEAD = ("수락하신", "제안대로", "말씀하신 대로", "적으신", "as you accepted", "as you confirmed")
# The acknowledgement counts only next to a present or future step; "말씀하신 대로 100 bar는
# 높습니다." is an answer, not a stall.
_PROMISES_STEP = ("넣습니다", "넣겠습니다", "검증합니다", "검사합니다", "진행합니다", "진행하겠습니다", "만들겠습니다", "저장하겠습니다", "i'll ", "i will ")

FOLLOW_UP_MESSAGE = (
    "(automatic) Your last message announced a tool step but made no tool call. "
    "Make that call now. If you are waiting for the user's answer instead, say in one "
    "short sentence what you need from them."
)
ANSWER_AFTER_TOOLS_MESSAGE = (
    "(automatic) You returned no reply after the tool results. Answer the user now from "
    "those results, or make the next tool call the request still needs."
)


def announces_unmade_step(text: str) -> bool:
    """The last paragraph promises a tool step and nothing in the text waits on the user."""
    folded = text.casefold().replace("’", "'")
    if not folded.strip() or any(marker in folded for marker in _WAITS_ON_USER):
        return False
    last = [part for part in folded.split("\n\n") if part.strip()][-1]
    return any(verb in last for verb in _STEP_VERBS) or any(step in last for step in _EN_STEPS)


def acknowledges_without_acting(text: str) -> bool:
    """The text confirms the user's go-ahead and nothing in it waits on the user.

    Only meaningful before the turn's first tool call; afterwards the same words close a
    finished step.
    """
    folded = text.casefold().replace("’", "'")
    if any(marker in folded for marker in _WAITS_ON_USER):
        return False
    return any(marker in folded for marker in _ACKNOWLEDGES_GO_AHEAD) and any(
        step in folded for step in _PROMISES_STEP
    )
