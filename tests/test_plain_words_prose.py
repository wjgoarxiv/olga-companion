from olga_companion.agent import tools
from olga_companion.agent.runtime import SYSTEM_PROMPT, build_system_prompt


def _normalized(prompt: str) -> str:
    return " ".join(prompt.lower().split())


def test_prompt_requires_plain_words_for_actions_and_fields() -> None:
    for prompt in (SYSTEM_PROMPT, build_system_prompt(), build_system_prompt(native_tab=True)):
        lowered = _normalized(prompt)
        assert "plain words" in lowered
        assert "only inside code" in lowered
        assert "technical detail" in lowered


def test_prompt_names_the_raw_ids_only_as_quoted_examples() -> None:
    lowered = _normalized(SYSTEM_PROMPT)
    for raw in ("output_interval_s", "max_dt_s", "diagnose_out", "run_patrol"):
        assert raw in lowered


def test_tool_names_are_unchanged() -> None:
    assert "run_patrol" in tools.TOOLS
    assert "diagnose_out" in tools.TOOLS
