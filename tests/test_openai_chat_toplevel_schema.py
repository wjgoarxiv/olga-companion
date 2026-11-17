"""Anthropic-compatible openai-chat tool payload.

Anthropic's OpenAI-compatible endpoint rejects top-level oneOf/anyOf/allOf in
tool parameters (`input_schema does not support oneOf, allOf, or anyOf at the
top level`). The openai-chat adapter must strip those keys from the provider
payload only and state the removed rule in words. The server still enforces
the dropped rules at dispatch, so a stripped payload can never smuggle a bad
call past validation.
"""
from __future__ import annotations

import pytest

from olga_companion.agent import tools
from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient

_TOP_LEVEL_CONDITIONALS = ("oneOf", "anyOf", "allOf")


def _converted() -> dict[str, dict[str, object]]:
    return {
        item["function"]["name"]: item["function"]
        for item in OpenAIChatApiClient._convert_tools(tools.tool_specs())
    }


def test_every_converted_chat_tool_has_no_toplevel_conditionals() -> None:
    for name, function in _converted().items():
        parameters = function["parameters"]
        assert isinstance(parameters, dict), name
        assert not any(key in parameters for key in _TOP_LEVEL_CONDITIONALS), name


def test_report_markdown_description_states_criterion_rule() -> None:
    function = _converted()["report_markdown"]
    assert function["parameters"].get("allOf") is None
    assert (
        "When criterion is given, ppl, flowpath and pipe are also required."
        in function["description"]
    )


def test_case_edit_plan_description_states_source_rule() -> None:
    function = _converted()["case_edit_plan"]
    assert function["parameters"].get("allOf") is None
    assert "When source is given" in function["description"]


def test_only_two_tools_carry_toplevel_conditionals() -> None:
    names = {
        spec["name"]
        for spec in tools.tool_specs()
        if any(key in (spec["parameters"] or {}) for key in _TOP_LEVEL_CONDITIONALS)
    }
    assert names == {"case_edit_plan", "report_markdown"}


def test_case_edit_plan_description_narrows_the_closed_branch_to_fallback() -> None:
    from olga_companion.agent.case_transaction_schemas import DESTINATION_RULE

    function = _converted()["case_edit_plan"]
    assert function["parameters"].get("allOf") is None
    assert "When operations is given" not in function["description"]
    assert function["description"] == (
        "Plan reviewed, hash-bound CaseSpec edits. "
        f"{DESTINATION_RULE} "
        "When source is given, source, source_hash and operations are also required. "
        "When spec is given, spec, spec_hash and operations are also required. "
        "Additional conditional rules are enforced by the server."
    )


def test_report_markdown_description_has_no_fallback_note() -> None:
    function = _converted()["report_markdown"]
    assert function["description"] == (
        "Generate an auditable Markdown report with a Sources footer. "
        "When criterion is given, ppl, flowpath and pipe are also required."
    )


def test_source_tool_specs_keep_their_conditionals() -> None:
    by_name = {spec["name"]: spec for spec in tools.tool_specs()}
    assert by_name["report_markdown"]["parameters"]["allOf"] == [
        {"if": {"required": ["criterion"]}, "then": {"required": ["ppl", "flowpath", "pipe"]}}
    ]
    assert by_name["case_edit_plan"]["parameters"]["allOf"]


def test_report_markdown_criterion_without_outputs_is_refused_without_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["report_markdown"], "handler", lambda args: calls.append(args) or {}
    )

    with pytest.raises(tools.ToolError, match="ppl|flowpath|pipe|required|Invalid"):
        tools.dispatch("report_markdown", {"genkey": "case.genkey", "criterion": 2.5})

    assert calls == []


def test_case_edit_plan_source_with_a_forbidden_field_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["case_edit_plan"], "handler", lambda args: calls.append(args) or {}
    )

    with pytest.raises(tools.ToolError, match="unknown|additional|field|invalid"):
        tools.dispatch(
            "case_edit_plan",
            {
                "source": "a.genkey",
                "source_hash": "a" * 64,
                "operations": [{"op": "set_integration", "end_time_s": 60.0}],
                "raw_genkey": "publish without approval",
            },
        )

    assert calls == []


def test_case_edit_plan_source_missing_its_hash_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["case_edit_plan"], "handler", lambda args: calls.append(args) or {}
    )

    with pytest.raises(tools.ToolError, match="source_hash|required|Invalid"):
        tools.dispatch("case_edit_plan", {"source": "a.genkey", "operations": []})

    assert calls == []
