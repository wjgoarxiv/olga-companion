from olga_companion.agent.runtime import SYSTEM_PROMPT


def test_prompt_no_longer_tells_the_model_to_announce_unrun_tools() -> None:
    assert "If you have not run the tool, say so" not in SYSTEM_PROMPT


def test_prompt_marks_unbacked_values_without_per_turn_tool_narration() -> None:
    lowered = " ".join(SYSTEM_PROMPT.lower().split())

    assert "when a reply gives no engineering number or verdict, write nothing about tools" in lowered
    assert "do not narrate which tools you have or have not called" in lowered
    assert "state a value without a tool result" in lowered
    assert "mark it unverified in one short clause" in lowered
    assert "do not guess numbers" in lowered
    assert "never claim to have run a simulation you did not run through run_execute" in lowered
