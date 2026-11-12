"""Failing-first contracts for production Chat result and artifact capabilities."""

from __future__ import annotations

import pytest

from olga_companion.agent import tool_schemas, tools
from olga_companion.llm.agent_clients import _adapt_runtime_tools
from olga_companion.llm.antigravity.streaming import convert_tools_to_antigravity
from olga_companion.llm.openai_chat_adapter import OpenAIChatApiClient
from olga_companion.llm.openai_responses_adapter import OpenAIResponsesApiClient
from olga_companion.llm.protocol import fix_schema


def test_model_tool_inputs_are_closed_nested_json_schemas() -> None:
    # Given: the model-visible tool registry.
    specs = {spec["name"]: spec["parameters"] for spec in tools.tool_specs()}

    # When: representative nested collection schemas are inspected.
    csv_schema = specs["results_csv"]
    plot_schema = specs["results_plot"]
    evaluate_schema = specs["evaluate"]

    # Then: unknown fields are rejected and every array has a typed item schema.
    assert all(schema.get("additionalProperties") is False for schema in specs.values())
    assert csv_schema["properties"]["variables"]["items"] == {"type": "string"}
    assert plot_schema["properties"]["variables"]["items"] == {"type": "string"}
    assert evaluate_schema["properties"]["criteria"]["items"]["type"] == "object"
    assert evaluate_schema["properties"]["criteria"]["items"]["additionalProperties"] is False


def test_report_compare_variables_are_a_bounded_string_array() -> None:
    # Given: the report comparison input schema.
    parameters = tools.TOOLS["report_compare"].parameters

    # When: the variables field is inspected.
    variables = parameters["properties"]["variables"]

    # Then: callers can compare one or more explicit variables, never a flat string.
    assert variables == {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "minItems": 1,
        "maxItems": 32,
    }


@pytest.mark.parametrize(
    ("tool_name", "invalid_args"),
    [
        ("results_csv", {"path": "result.tpl", "variables": "TM"}),
        ("report_figure", {"kind": "executable", "file": "result.tpl", "branch": "OUTLET"}),
        ("results_load", {"path": "result.tpl", "unexpected": "field"}),
    ],
)
def test_invalid_nested_enum_and_unknown_inputs_stop_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    invalid_args: dict[str, str],
) -> None:
    # Given: an invalid provider tool call and an observable adapter seam.
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(tools.TOOLS[tool_name], "handler", lambda args: calls.append(args) or {})

    # When: server dispatch parses the untrusted call.
    with pytest.raises(tools.ToolError, match="invalid|schema|argument|field"):
        tools.dispatch(tool_name, invalid_args)

    # Then: malformed input never reaches the adapter.
    assert calls == []


def test_nested_schema_matches_every_provider_and_server_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one canonical nested schema crossing every active provider boundary.
    canonical = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "variables": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "selection": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "mode": {"type": "string", "enum": ["raw", "engineering"]},
                },
                "required": ["mode"],
            },
        },
        "required": ["variables", "selection"],
    }
    flat_spec = {"name": "schema_parity_probe", "description": "Probe", "parameters": canonical}
    adapted = _adapt_runtime_tools([flat_spec])
    assert adapted is not None

    # When: OpenAI Responses, OpenAI Chat/Copilot, and Antigravity convert it.
    provider_schemas = [
        OpenAIResponsesApiClient._convert_tools([flat_spec])[0]["parameters"],
        OpenAIChatApiClient._convert_tools(adapted)[0]["function"]["parameters"],
        convert_tools_to_antigravity([flat_spec])[0]["parameters"],
    ]

    # Then: wire schemas remain canonical and server dispatch enforces that schema.
    assert provider_schemas == [fix_schema(canonical)] * 3
    calls: list[bool] = []
    probe = tools.Tool("schema_parity_probe", "Probe", canonical, lambda _args: calls.append(True) or {})
    monkeypatch.setitem(tools.TOOLS, "schema_parity_probe", probe)
    with pytest.raises(tools.ToolError, match="invalid|schema|argument|field"):
        tools.dispatch(
            "schema_parity_probe",
            {"variables": ["TM"], "selection": {"mode": "unsupported"}},
        )
    assert calls == []


def test_chat_registry_exposes_result_inventory_and_bounded_series() -> None:
    # Given: the complete model capability registry.
    registry = tools.TOOLS

    # When: result discovery capabilities are selected.
    inventory = registry.get("results_inventory")
    series = registry.get("results_series")

    # Then: Chat can discover results and request a bounded numeric slice.
    assert inventory is not None
    assert series is not None
    assert series.parameters["additionalProperties"] is False
    assert series.parameters["properties"]["offset"] == {
        "type": "integer",
        "minimum": 0,
    }
    assert series.parameters["properties"]["row_limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 5000,
    }
    assert series.parameters["properties"]["truncation"] == {
        "type": "string",
        "enum": ["head", "tail", "uniform"],
    }
    assert series.parameters["properties"]["time_range"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "start": {"type": "number", "minimum": 0},
            "end": {"type": "number", "minimum": 0},
        },
        "required": ["start", "end"],
    }


def test_result_series_rejects_reversed_time_range_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a bounded series request with an impossible time selection.
    series = tools.TOOLS.get("results_series")
    assert series is not None
    calls: list[dict[str, str | int | dict[str, int]]] = []
    monkeypatch.setattr(series, "handler", lambda args: calls.append(args) or {})

    # When: server dispatch parses a range whose end precedes its start.
    with pytest.raises(tools.ToolError, match="time|range|start|end"):
        tools.dispatch(
            "results_series",
            {
                "result_id": "result-1",
                "variable": "TM",
                "row_limit": 100,
                "time_range": {"start": 20, "end": 10},
            },
        )

    # Then: invalid selection cannot reach the result adapter.
    assert calls == []


def test_result_inventory_declares_source_identity_and_lineage_output() -> None:
    # Given: a result inventory tool intended for provider dispatch.
    inventory = tools.TOOLS.get("results_inventory")

    # When: its typed response contract is inspected.
    response_schema = None if inventory is None else getattr(inventory, "response_schema", None)

    # Then: every entry carries stable source identity, hash, and provenance.
    assert response_schema is not None
    assert response_schema["additionalProperties"] is False
    item = response_schema["properties"]["results"]["items"]
    assert item["additionalProperties"] is False
    assert {
        "result_id",
        "name",
        "kind",
        "source_sha256",
        "lineage",
    } <= set(item["required"])


def test_result_series_declares_bounded_numeric_table_output() -> None:
    # Given: a result series tool intended for semantic table rendering.
    series = tools.TOOLS.get("results_series")

    # When: its typed response contract is inspected.
    response_schema = None if series is None else getattr(series, "response_schema", None)

    # Then: pagination, units, position, lineage, and truncation are explicit.
    assert response_schema is not None
    assert response_schema["additionalProperties"] is False
    required = set(response_schema["required"])
    assert {
        "rows",
        "variable",
        "row_limit",
        "total_rows",
        "returned_rows",
        "units",
        "position",
        "time_range",
        "source_sha256",
        "truncated",
        "truncation",
    } <= required
    assert response_schema["properties"]["time_range"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "start": {"type": "number"},
            "end": {"type": "number"},
        },
        "required": ["start", "end"],
    }
    row = response_schema["properties"]["rows"]["items"]
    assert row == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "time": {"type": "number"},
            "value": {"type": "number"},
        },
        "required": ["time", "value"],
    }


def test_artifact_receipt_is_opaque_hash_bound_and_actionable() -> None:
    # Given: the shared artifact receipt schema used by Chat exports.
    receipt = getattr(tool_schemas, "ARTIFACT_RECEIPT_SCHEMA", None)

    # When: its trust-boundary fields are inspected.
    assert receipt is not None
    properties = receipt["properties"]

    # Then: no absolute path is required and all integrity/action fields are typed.
    assert receipt["additionalProperties"] is False
    assert {
        "artifact_id",
        "kind",
        "mime",
        "size_bytes",
        "sha256",
        "suggested_filename",
        "lineage",
        "workspace_generation",
        "actions",
    } <= set(receipt["required"])
    assert "path" not in properties
    assert properties["kind"]["enum"] == ["csv", "png", "pdf"]
    assert properties["mime"]["enum"] == ["text/csv", "image/png", "application/pdf"]
    assert properties["sha256"] == {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    assert properties["actions"]["items"]["enum"] == [
        "download",
        "open_in_results",
        "native_save_as",
    ]


def test_export_tools_share_the_artifact_receipt_response_contract() -> None:
    # Given: every Chat tool that produces a user-visible export.
    producers = ("results_csv", "results_plot", "report_figure")
    receipt = getattr(tool_schemas, "ARTIFACT_RECEIPT_SCHEMA", None)

    # When: their response contracts are inspected.
    response_schemas = [getattr(tools.TOOLS[name], "response_schema", None) for name in producers]

    # Then: CSV, PNG, and PDF all return one opaque receipt shape.
    assert receipt is not None
    assert response_schemas == [receipt, receipt, receipt]


def test_native_save_as_requires_a_human_destination_and_terminal_receipt() -> None:
    # Given: the native Save As action contract linked from an artifact receipt.
    contract = getattr(tool_schemas, "NATIVE_SAVE_AS_ACTION_SCHEMA", None)

    # When: cancellation and terminal success semantics are inspected.
    assert contract is not None
    properties = contract["properties"]

    # Then: Chat cannot preselect success and only a dialog receipt proves saving.
    assert contract["additionalProperties"] is False
    assert properties["requires_human_destination"]["const"] is True
    assert properties["status"]["enum"] == [
        "available",
        "dialog_open",
        "saved",
        "cancelled",
        "failed",
    ]
    assert "save_receipt" in properties


def test_model_side_effect_registry_gates_save_and_cancellation() -> None:
    # Given: model-visible tools that can mutate workspace or running processes.
    side_effects = ("genkey_save", "run_cancel", "sweep_cancel")

    # When: their dispatch classification is inspected.
    gated = {name: tools.TOOLS[name].side_effect for name in side_effects}

    # Then: every model request stops at the human approval boundary.
    assert gated == {name: True for name in side_effects}


def test_direct_human_emergency_stop_is_not_a_model_tool() -> None:
    # Given: the direct-human action registry and model capability registry.
    actions = getattr(tool_schemas, "DIRECT_HUMAN_ACTIONS", None)

    # When: the emergency stop concept is inspected.
    assert actions is not None

    # Then: it is authenticated/immediate for humans and absent from model tools.
    assert actions["run_emergency_stop"] == {
        "actor": "human",
        "approval_required": False,
        "authenticated": True,
        "immediate": True,
    }
    assert "run_emergency_stop" not in tools.TOOLS
