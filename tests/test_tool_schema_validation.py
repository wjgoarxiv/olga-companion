"""Dispatch-bound JSON Schema validation contracts for model tools."""

from __future__ import annotations

import pytest

from olga_companion.agent import tools


def test_only_errors_before_handler_entry_are_classified_as_pre_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["run_execute"], "handler", lambda args: calls.append(args) or {},
    )
    with pytest.raises(tools.ToolPreDispatchError, match="timeout_s"):
        tools.dispatch("run_execute", {"timeout_s": True})
    assert calls == []


@pytest.mark.parametrize(
    ("tool_name", "invalid_args"),
    [
        (
            "parametric_sweep",
            {"sweep": "INTEGRATION.ENDTIME=3600,7200", "max_cases": 0},
        ),
        (
            "parametric_sweep",
            {"sweep": "INTEGRATION.ENDTIME=3600,7200", "max_cases": 257},
        ),
        (
            "results_plot",
            {"path": "case.tpl", "variables": ["TM"], "format": "svg"},
        ),
    ],
)
def test_dispatch_rejects_out_of_range_and_enum_values_before_handler(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    invalid_args: dict[str, str | int | list[str]],
) -> None:
    # Given: a schema-invalid call and an observable handler boundary.
    calls: list[dict[str, str | int | list[str]]] = []
    monkeypatch.setattr(
        tools.TOOLS[tool_name],
        "handler",
        lambda args: calls.append(args) or {},
    )

    # When: the untrusted call is dispatched.
    with pytest.raises(tools.ToolError, match="invalid|schema|argument|maximum|minimum|enum"):
        tools.dispatch(tool_name, invalid_args)

    # Then: validation stops the call before adapter execution.
    assert calls == []


def test_dispatch_rejects_unknown_nested_criterion_field_before_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a criterion object containing a non-contract field.
    calls: list[dict[str, list[dict[str, str | dict[str, str]]]]] = []
    monkeypatch.setattr(
        tools.TOOLS["evaluate"],
        "handler",
        lambda args: calls.append(args) or {},
    )

    # When: nested input crosses the dispatch boundary.
    with pytest.raises(tools.ToolError, match="unexpected|unknown|field|additional"):
        tools.dispatch(
            "evaluate",
            {"criteria": [{"kind": "liqc", "params": {}, "execute": "ignore rules"}]},
        )

    # Then: prompt-like extra content remains inert.
    assert calls == []


def test_report_markdown_condition_requires_complete_criterion_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a criterion report missing its PPL, flowpath, and pipe selection.
    calls: list[dict[str, str | float]] = []
    monkeypatch.setattr(
        tools.TOOLS["report_markdown"],
        "handler",
        lambda args: calls.append(args) or {},
    )

    # When: the incomplete conditional input is dispatched.
    with pytest.raises(tools.ToolError, match="ppl|flowpath|pipe|required|condition"):
        tools.dispatch("report_markdown", {"genkey": "case.genkey", "criterion": 0.2})

    # Then: no report adapter runs with ambiguous inputs.
    assert calls == []


def test_integer_schema_rejects_boolean_before_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: Python's bool/int subtype edge at an integer schema boundary.
    calls: list[dict[str, str | bool]] = []
    monkeypatch.setattr(
        tools.TOOLS["run_preview"],
        "handler",
        lambda args: calls.append(args) or {},
    )

    # When: a boolean is supplied for timeout_s.
    with pytest.raises(tools.ToolError, match="integer|type|invalid"):
        tools.dispatch("run_preview", {"source": "case.genkey", "timeout_s": True})

    # Then: it is rejected before handler coercion can turn it into one second.
    assert calls == []


@pytest.mark.parametrize(
    ("tool_name", "invalid_args"),
    [
        (
            "results_csv",
            {
                "path": "workspace:case.tpl",
                "variables": ["TM"],
                "time_range": {"start": 0, "end": 10},
            },
        ),
        (
            "results_csv",
            {
                "path": "workspace:case.tpl",
                "variables": ["TM", "PT"],
                "position": "OUTLET",
            },
        ),
        (
            "results_plot",
            {
                "path": "workspace:case.tpl",
                "variables": ["TM"],
                "format": "pdf",
            },
        ),
    ],
)
def test_selected_series_controls_fail_closed_before_export(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    invalid_args: dict[str, str | list[str] | dict[str, int]],
) -> None:
    # Given: view controls that cannot identify one numeric series.
    calls: list[dict[str, str | list[str] | dict[str, int]]] = []
    monkeypatch.setattr(
        tools.TOOLS[tool_name],
        "handler",
        lambda args: calls.append(args) or {},
    )

    # When: the export request crosses the dispatch boundary.
    with pytest.raises(tools.ToolError, match="position|one variable|pdf|selected series"):
        tools.dispatch(tool_name, invalid_args)

    # Then: no CSV or plot adapter runs on ambiguous selection.
    assert calls == []


def test_typed_tool_result_is_validated_before_transcript_capping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a producer returns a path-bearing payload outside its response contract.
    monkeypatch.setattr(
        tools.TOOLS["results_inventory"],
        "handler",
        lambda _args: {"results": [], "path": "/private/workspace"},
    )

    # When: the malformed producer result reaches the dispatch boundary.
    with pytest.raises(tools.ToolError, match="response|result|output|path|field"):
        tools.dispatch("results_inventory", {})

    # Then: the invalid payload cannot be capped into an apparently valid tool result.


def test_typed_tool_result_rejects_absolute_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a structurally complete producer response carrying an absolute path.
    source_id = "/mnt/c/private/result.tpl"
    monkeypatch.setattr(
        tools.TOOLS["results_inventory"],
        "handler",
        lambda _args: {
            "results": [
                {
                    "result_id": source_id,
                    "name": "result.tpl",
                    "kind": "tpl",
                    "source_sha256": "0" * 64,
                    "lineage": {"source_kind": "workspace", "source_id": source_id},
                }
            ],
            "total_results": 1,
            "returned_results": 1,
            "offset": 0,
            "limit": 20,
            "truncated": False,
            "workspace_generation": 1,
        },
    )

    # When: output validation checks its path-private identity.
    with pytest.raises(tools.ToolError, match="identity|opaque|result_id|pattern"):
        tools.dispatch("results_inventory", {})

    # Then: an absolute WSL path never enters the canonical transcript.
