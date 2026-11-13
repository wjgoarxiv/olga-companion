"""The in-app table generator as an agent tool (plan todo 5, local PVT builds only).

Offline. The OLGA process launch is the only fake: the table is written by the real
independent engine, checked by the real validator, and published by the real case
publisher in a temporary workspace.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from olga_companion import config, fluid_table, runner, workspace
from olga_companion.agent import (
    approval_display,
    approval_execution,
    approvals,
    chat,
    history,
    pending_approvals,
    plan_model,
    runtime,
    session_token,
    tool_schemas,
    tools,
)
from olga_companion.agent.tool_validation import ToolError, ToolFailedError, ToolRefusedError
from olga_companion.llm.protocol import StreamResult, ToolCall

FLAG = "OLGA_COMPANION_NATIVE_TAB"
SRC = str(Path(__file__).resolve().parents[1] / "src")
TOOL = "fluids_generate_tab"
NOTE = "independent table, not multiflash-identical"

GEN: dict[str, Any] = {
    "fluid_label": "SYN_CO2",
    "components": [
        {"name": "CO2", "mole_fraction": 0.95},
        {"name": "N2", "mole_fraction": 0.03},
        {"name": "CH4", "mole_fraction": 0.02},
    ],
    "model": "PR",
    "temperatures": [-10, 0, 10, 20],
    "temperature_unit": "degC",
    "pressures": [10, 20, 30],
    "pressure_unit": "bar",
    "tab_rel": "syn_co2.tab",
}


def _gen(**changes: Any) -> dict[str, Any]:
    return {**json.loads(json.dumps(GEN)), **changes}


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.delenv(FLAG, raising=False)
    session_token.boot_token()
    pending_approvals.revoke_all()
    yield root
    pending_approvals.revoke_all()
    chat.set_client_builder(None)


@pytest.fixture
def root(_workspace: Path) -> Path:
    return _workspace


@pytest.fixture
def gen() -> int:
    return workspace.context_generation()


@pytest.fixture
def native_on(monkeypatch: pytest.MonkeyPatch):
    """The local PVT build: the flag is set and the registry is built with it."""
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setattr(tools, "TOOLS", tool_schemas.build_tools(tools._HANDLERS))
    monkeypatch.setattr(runtime, "SYSTEM_PROMPT", runtime.build_system_prompt())


def _approved(kind: str, args: dict[str, Any], generation: int) -> dict[str, Any]:
    payload = tools.approval_payload(kind, args)
    token = approvals.mint(kind, payload, context_generation=generation)["token"]
    return {**args, "approval_token": token, "idempotency_key": "k" * 32}


def _names(specs: list[dict[str, Any]]) -> set[str]:
    return {spec["name"] for spec in specs}


# ------------------------------------------------------------------ the flag


@pytest.mark.parametrize(
    ("value", "enabled"),
    [(None, False), ("", False), ("0", False), ("true", False), ("yes", False), ("1", True)],
)
def test_the_flag_is_exactly_one(monkeypatch: pytest.MonkeyPatch, value: str | None, enabled: bool) -> None:
    if value is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, value)
    assert config.native_tab_enabled() is enabled


def test_flag_off_the_tool_is_absent_from_the_registry_and_the_model_specs() -> None:
    assert TOOL not in tools.TOOLS
    assert TOOL not in _names(tools.tool_specs())
    plan = next(spec for spec in tools.tool_specs() if spec["name"] == "action_plan")
    kinds = plan["parameters"]["properties"]["steps"]["items"]["properties"]["kind"]["enum"]
    assert TOOL not in kinds
    assert TOOL not in plan["description"]
    edit = next(spec for spec in tools.tool_specs() if spec["name"] == "case_edit_plan")
    assert "pending_table" not in edit["parameters"]["properties"]


def test_flag_off_the_tool_cannot_be_dispatched_priced_or_planned(root: Path, gen: int) -> None:
    with pytest.raises(tools.ToolPreDispatchError):
        tools.dispatch(TOOL, _gen())
    with pytest.raises(ToolError):
        tools.approval_payload(TOOL, _gen())
    with pytest.raises(ToolError, match="not available"):
        tools.approval_payload("action_plan", {"steps": [{"kind": TOOL, "args": _gen()}]})
    assert not (root / "syn_co2.tab").exists()


def test_flag_off_the_prompt_never_mentions_the_generator() -> None:
    lowered = runtime.build_system_prompt(native_tab=False).casefold()
    assert runtime.SYSTEM_PROMPT == runtime.build_system_prompt(native_tab=False)
    for word in (TOOL, "independent table", "multiflash-identical", "native_tab", "pvt_engine"):
        assert word not in lowered
    assert "fluids_draft_mfl" in lowered


def _fresh_interpreter(flag: str | None) -> dict[str, Any]:
    script = (
        "import json, sys\n"
        f"sys.path.insert(0, {SRC!r})\n"
        "from olga_companion.agent import tools, runtime\n"
        "print(json.dumps({'tool': 'fluids_generate_tab' in tools.TOOLS,\n"
        "  'prompt': 'fluids_generate_tab' in runtime.SYSTEM_PROMPT,\n"
        "  'engine': 'olga_companion.pvt_engine' in sys.modules,\n"
        "  'adapter': 'olga_companion.native_tab' in sys.modules}))\n"
    )
    env = {key: value for key, value in os.environ.items() if key != FLAG}
    if flag is not None:
        env[FLAG] = flag
    done = subprocess.run(
        [sys.executable, "-I", "-c", script], env=env, capture_output=True, text=True, timeout=120, check=True
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_fresh_process_without_the_flag_loads_no_engine_and_no_tool() -> None:
    assert _fresh_interpreter(None) == {"tool": False, "prompt": False, "engine": False, "adapter": False}
    assert _fresh_interpreter("0") == {"tool": False, "prompt": False, "engine": False, "adapter": False}


def test_a_fresh_process_with_the_flag_registers_the_tool_and_the_prompt() -> None:
    seen = _fresh_interpreter("1")
    assert seen["tool"] is True and seen["prompt"] is True


# ------------------------------------------------------- schema and the card


def test_the_tool_is_a_closed_approval_gated_side_effect(native_on: None) -> None:
    tool = tools.TOOLS[TOOL]
    assert tool.side_effect is True
    properties = tool.parameters["properties"]
    assert tool.parameters["additionalProperties"] is False
    assert {
        "fluid_label", "components", "model", "temperatures", "temperature_unit",
        "pressures", "pressure_unit", "tab_rel", "approval_token", "idempotency_key",
    } == set(properties)
    assert set(tool.parameters["required"]) == {
        "fluid_label", "components", "model", "temperatures", "temperature_unit",
        "pressures", "pressure_unit", "tab_rel", "approval_token", "idempotency_key",
    }
    assert properties["temperatures"]["maxItems"] <= 100 and properties["pressures"]["maxItems"] <= 100
    spec = next(item for item in tools.tool_specs() if item["name"] == TOOL)
    assert "approval_token" not in spec["parameters"]["properties"]
    assert "idempotency_key" not in spec["parameters"]["required"]
    text = json.dumps(spec)
    for model in ("PR", "PR78", "SRK"):
        assert model in text
    for name in ("CO2", "N2", "CH4", "C2H6", "C3H8", "iC4", "nC4", "H2S"):
        assert name in text
    assert NOTE in spec["description"].casefold()


def test_the_plan_tool_offers_the_generator_only_with_the_flag(native_on: None) -> None:
    plan = next(spec for spec in tools.tool_specs() if spec["name"] == "action_plan")
    kinds = plan["parameters"]["properties"]["steps"]["items"]["properties"]["kind"]["enum"]
    assert TOOL in kinds
    assert TOOL in plan["description"]
    assert TOOL in plan_model.offered_kinds()


def test_the_payload_is_canonical_and_free_of_credentials(native_on: None, root: Path) -> None:
    payload = tools.approval_payload(
        TOOL,
        _gen(
            components=[{"name": "carbon dioxide", "mole_fraction": 0.9}, {"name": "methane", "mole_fraction": 0.1}],
            temperature_unit="C",
            pressure_unit="BARG",
        ),
    )
    assert payload["tab_rel"] == "syn_co2.tab"
    assert payload["fluid_label"] == "SYN_CO2"
    assert payload["model"] == "PR"
    assert payload["components"] == [
        {"name": "CO2", "mole_fraction": 0.9}, {"name": "CH4", "mole_fraction": 0.1},
    ]
    assert (payload["temperature_unit"], payload["pressure_unit"]) == ("degC", "barg")
    assert payload["temperatures"] == [-10.0, 0.0, 10.0, 20.0]
    assert "approval_token" not in json.dumps(payload)


# ----------------------------------------------------------- precheck, no card


@pytest.mark.parametrize(
    ("changes", "needle"),
    [
        ({"components": [{"name": "unobtainium", "mole_fraction": 1.0}]}, "CO2"),
        ({"temperature_unit": "furlong"}, "temperature unit"),
        ({"pressure_unit": "furlong"}, "pressure unit"),
        ({"components": [{"name": "CO2", "mole_fraction": 0.5}, {"name": "N2", "mole_fraction": 0.4}]}, "sum"),
        ({"model": "NRTL"}, "PR78"),
        ({"model": "PRA"}, "PR78"),
        ({"temperatures": [-70, -60, -50]}, "triple point"),
        ({"temperatures": [20, 10, 0]}, "increasing"),
        ({"temperatures": [10]}, "two"),
        ({"pressures": [1, 50_000]}, "window"),
        ({"fluid_label": "bad label"}, "label"),
        ({"tab_rel": "syn_co2.txt"}, ".tab"),
        ({"tab_rel": "../escape.tab"}, "workspace"),
        ({"tab_rel": "no_such_folder/x.tab"}, "folder"),
        (
            {"components": [{"name": "CO2", "mole_fraction": 0.5}, {"name": "carbon dioxide", "mole_fraction": 0.5}]},
            "once",
        ),
    ],
)
def test_a_bad_request_is_refused_before_any_card_and_writes_nothing(
    native_on: None, root: Path, changes: dict[str, Any], needle: str
) -> None:
    with pytest.raises(ToolError) as caught:
        tools.approval_payload(TOOL, _gen(**changes))
    assert needle.casefold() in str(caught.value).casefold()
    assert sorted(path.name for path in root.iterdir()) == []


def test_an_existing_table_or_report_is_refused_without_a_card(native_on: None, root: Path) -> None:
    (root / "syn_co2.tab").write_text("keep me\n", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        tools.approval_payload(TOOL, _gen())
    (root / "syn_co2.tab").unlink()
    (root / "syn_co2.fill.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        tools.approval_payload(TOOL, _gen())


def test_the_runtime_answers_a_bad_request_without_a_card(native_on: None, gen: int) -> None:
    class Client:
        def create_conversation(self, model: str = ""):
            class Conversation:
                def add_user_message(self, *a, **k): ...
                def add_assistant_response(self, *a, **k): ...
                def add_tool_result(self, *a, **k): ...

            return Conversation()

        async def stream_generate(self, **_kwargs):
            bad = _gen(temperatures=[-70, -60, -50])
            return StreamResult(tool_calls=[ToolCall(name=TOOL, args=bad, call_id="g-1")])

    client = Client()

    async def collect():
        return [
            event
            async for event in runtime.run_turn(
                client, "go", model="m", conversation=client.create_conversation(),
                context_generation=gen, max_iterations=1,
            )
        ]

    events = asyncio.run(collect())
    assert not [event for event in events if event.type == "approval_required"]
    answer = [event for event in events if event.type == "tool_result"]
    assert answer and "triple point" in answer[0].data["result"]["error"]


def test_the_runtime_raises_one_card_for_a_good_request(native_on: None, gen: int) -> None:
    class Client:
        def create_conversation(self, model: str = ""):
            class Conversation:
                def add_user_message(self, *a, **k): ...
                def add_assistant_response(self, *a, **k): ...
                def add_tool_result(self, *a, **k): ...

            return Conversation()

        async def stream_generate(self, **_kwargs):
            return StreamResult(tool_calls=[ToolCall(name=TOOL, args=_gen(), call_id="g-1")])

    client = Client()

    async def collect():
        return [
            event
            async for event in runtime.run_turn(
                client, "go", model="m", conversation=client.create_conversation(),
                context_generation=gen, max_iterations=1,
            )
        ]

    events = asyncio.run(collect())
    cards = [event for event in events if event.type == "approval_required"]
    assert [card.data["name"] for card in cards] == [TOOL]


# ---------------------------------------------------------------- unit helpers


def test_grid_values_convert_from_every_supported_unit() -> None:
    from olga_companion import native_tab

    assert native_tab.to_celsius([0, 100], "degC") == [0.0, 100.0]
    assert native_tab.to_celsius([273.15, 373.15], "K") == pytest.approx([0.0, 100.0])
    assert native_tab.to_celsius([32, 212], "degF") == pytest.approx([0.0, 100.0])
    assert native_tab.to_celsius([491.67, 671.67], "degR") == pytest.approx([0.0, 100.0])
    assert native_tab.to_pascal([1, 2], "bar") == pytest.approx([100_000.0, 200_000.0])
    assert native_tab.to_pascal([0, 5], "barg") == pytest.approx([101_325.0, 601_325.0])
    assert native_tab.to_pascal([1], "atm") == pytest.approx([101_325.0])
    assert native_tab.to_pascal([0], "atmg") == pytest.approx([101_325.0])
    assert native_tab.to_pascal([14.5], "psi") == pytest.approx([99_974.0], rel=1e-4)
    assert native_tab.to_pascal([0], "psig") == pytest.approx([101_325.0])
    assert native_tab.to_pascal([1], "Mpa") == pytest.approx([1_000_000.0])
    assert native_tab.to_pascal([100], "kPa") == pytest.approx([100_000.0])
    assert native_tab.to_pascal([760], "mmHg") == pytest.approx([101_325.0], rel=1e-4)
    assert native_tab.to_pascal([1], "at") == pytest.approx([98_066.5])
    assert native_tab.to_pascal([0], "atg") == pytest.approx([101_325.0])
    assert native_tab.to_pascal([0], "inwg") == pytest.approx([101_325.0])
    assert native_tab.to_pascal([5], "Pa") == [5.0]


def test_every_pressure_and_temperature_keyword_has_a_conversion() -> None:
    from olga_companion import native_tab

    for unit in fluid_table.SUPPORTED_PRESSURE_UNITS:
        assert native_tab.to_pascal([1], unit)
    for unit in fluid_table.SUPPORTED_TEMPERATURE_UNITS:
        assert native_tab.to_celsius([300], unit)


def test_the_adapter_lists_the_engine_models_by_name() -> None:
    from olga_companion import native_tab

    assert native_tab.MODELS == ("PR", "PR78", "SRK")
    assert "CO2" in native_tab.COMPONENTS and "iC4" in native_tab.COMPONENTS


# -------------------------------------------------------------- the real write


def test_dispatch_writes_a_table_that_passes_the_validator(native_on: None, root: Path, gen: int) -> None:
    result = tools.dispatch(TOOL, _approved(TOOL, _gen(), gen))

    table = root / "syn_co2.tab"
    assert table.is_file()
    assert result["ok"] is True and result["tab_rel"] == "syn_co2.tab"
    assert result["validator"]["valid"] is True and result["validator"]["error_count"] == 0
    assert isinstance(result["validator"]["warning_count"], int)
    assert result["node_count"] == 12
    report = json.loads((root / "syn_co2.fill.json").read_text(encoding="utf-8"))
    assert result["filled_node_count"] == report["filled_node_count"]
    assert result["fill_report_rel"] == "syn_co2.fill.json"
    assert result["declared_label"] == "SYN_CO2"
    assert NOTE in result["table_kind"].casefold()
    head = table.read_text(encoding="utf-8")
    assert "Independent table, not Multiflash-identical" in head
    assert 'PVTTABLE LABEL = "SYN_CO2"' in head
    assert fluid_table.pickup_tab(str(table), "SYN_CO2")["valid"] is True


def test_dispatch_converts_gauge_and_fahrenheit_grids(native_on: None, root: Path, gen: int) -> None:
    args = _gen(
        temperatures=[14, 32, 50, 68], temperature_unit="degF",
        pressures=[0, 10], pressure_unit="barg", tab_rel="g.tab",
    )
    tools.dispatch(TOOL, _approved(TOOL, args, gen))

    text = (root / "g.tab").read_text(encoding="utf-8")
    assert "PRESSURE = ( 101325, 1101325 ) PA" in text
    assert "TEMPERATURE = ( -10, 0, 10, 20 ) C" in text


def test_the_table_is_never_overwritten(native_on: None, root: Path, gen: int) -> None:
    args = _approved(TOOL, _gen(), gen)
    (root / "syn_co2.tab").write_text("owner file\n", encoding="utf-8")

    with pytest.raises(ToolError, match="already exists"):
        tools.dispatch(TOOL, args)

    assert (root / "syn_co2.tab").read_text(encoding="utf-8") == "owner file\n"
    assert not (root / "syn_co2.fill.json").exists()


def test_an_engine_refusal_after_the_card_writes_nothing_and_reads_as_refused(
    native_on: None, root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import native_tab

    approved = _approved(TOOL, _gen(), gen)

    def refuse(*_a: Any, **_k: Any):
        raise native_tab.NativeTabError("Node P=1e6 Pa: the flash did not converge; nothing was written.")

    monkeypatch.setattr(native_tab, "generate", refuse)
    with pytest.raises(ToolRefusedError, match="did not converge"):
        tools.dispatch(TOOL, approved)
    assert sorted(path.name for path in root.iterdir()) == []


def _reject_every_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        fluid_table, "pickup_tab",
        lambda *_a, **_k: {
            "found": True, "valid": False, "declared_label": "SYN_CO2", "label_match": True,
            "errors": [{"code": "V999", "message": "column order is wrong"}], "warnings": [],
        },
    )


def test_a_table_the_validator_rejects_stops_the_step_and_is_kept_for_inspection(
    native_on: None, root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = _approved(TOOL, _gen(), gen)
    _reject_every_table(monkeypatch)

    # The file is already written, so this is a known failure, never "refused before it started".
    with pytest.raises(ToolFailedError, match="validator") as caught:
        tools.dispatch(TOOL, approved)

    assert not isinstance(caught.value, ToolRefusedError)
    text = str(caught.value)
    assert "column order is wrong" in text
    assert "syn_co2.tab" in text
    assert "do not link" in text.casefold()
    assert "nothing was linked" not in text.casefold()
    assert (root / "syn_co2.tab").is_file()


def test_the_approval_is_single_use(native_on: None, root: Path, gen: int) -> None:
    approved = _approved(TOOL, _gen(), gen)
    tools.dispatch(TOOL, approved)
    first = (root / "syn_co2.tab").read_bytes()

    with pytest.raises(ToolError):
        tools.dispatch(TOOL, approved)

    assert (root / "syn_co2.tab").read_bytes() == first


def test_the_handler_needs_a_server_capability(native_on: None, root: Path) -> None:
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, _gen())
    assert not (root / "syn_co2.tab").exists()


def test_one_card_click_writes_the_table_through_the_real_approval_route(
    native_on: None, root: Path, gen: int
) -> None:
    session_id = history.new_session("gen")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args=_gen(), call_id="g-1", context_generation=gen, session_id=session_id
    )

    body = approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="g-1", context_generation=gen
    )

    assert (root / "syn_co2.tab").is_file()
    assert body["result"]["validator"]["valid"] is True
    assert body["result"]["filled_node_count"] >= 0


# ----------------------------------------------------------------- card fields


def test_the_card_lists_file_label_composition_model_and_grid_in_english(native_on: None, root: Path) -> None:
    shown = approval_display.build(TOOL, _gen(), locale="en")
    rows = {row["key"]: row for row in shown["fields"] if row["key"] != "component"}
    components = [row["value"] for row in shown["fields"] if row["key"] == "component"]

    assert rows["file"]["value"] == "syn_co2.tab"
    assert rows["label"]["value"] == "SYN_CO2"
    assert rows["model"]["value"] == "PR"
    assert components == ["CO2 0.95", "N2 0.03", "CH4 0.02"]
    assert (rows["temperature_range"]["value"], rows["temperature_range"]["unit"]) == ("-10 – 20", "degC")
    assert (rows["pressure_range"]["value"], rows["pressure_range"]["unit"]) == ("10 – 30", "bar")
    assert rows["temperature_points"]["value"] == "4" and rows["pressure_points"]["value"] == "3"
    assert NOTE in rows["table_kind"]["value"].casefold()
    assert "approval_token" not in json.dumps(shown)


def test_the_card_note_is_korean_for_a_korean_locale(native_on: None, root: Path) -> None:
    shown = approval_display.build(TOOL, _gen(), locale="ko")
    note = next(row["value"] for row in shown["fields"] if row["key"] == "table_kind")
    assert "독립" in note and "Multiflash" in note
    assert NOTE not in note.casefold()


def test_a_plan_row_for_the_generator_carries_the_same_fields(native_on: None, root: Path) -> None:
    shown = approval_display.build("action_plan", {"steps": [{"kind": TOOL, "args": _gen()}]}, locale="en")

    row = shown["plan"]["steps"][0]
    assert row["kind"] == TOOL
    assert {"file", "label", "model", "temperature_range", "pressure_range", "table_kind"} <= {
        field["key"] for field in row["fields"]
    }


# ------------------------------------------------------- the prompt (flag on)


def test_prompt_with_the_flag_walks_the_in_app_generator_first(native_on: None) -> None:
    prompt = runtime.build_system_prompt(native_tab=True)
    assert prompt == runtime.SYSTEM_PROMPT
    lowered = prompt.casefold()
    assert TOOL in prompt
    assert lowered.count(NOTE) == 1
    for model in ("PR", "PR78", "SRK"):
        assert model in prompt
    assert prompt.index(TOOL) < prompt.index("fluids_draft_mfl", prompt.index(TOOL))
    for step in ("composition", "model", "grid", "validate", "link"):
        assert step in lowered
    assert "never invent" in lowered and "bip" in lowered
    assert "multiflash" in lowered and ".mfl" in lowered
    assert "company standard" not in lowered
    assert "one action_plan" in lowered or "single action_plan" in lowered or "one approval" in lowered
    assert "pending_table" in prompt


def test_the_plan_bullet_of_the_prompt_lists_the_generator_as_a_step(native_on: None) -> None:
    prompt = runtime.build_system_prompt(native_tab=True)
    bullet = prompt[prompt.index("action_plan once"):]
    assert "fluids_generate_tab" in bullet[:700]


def test_the_existing_prompt_text_is_unchanged_for_release_builds() -> None:
    off = runtime.build_system_prompt(native_tab=False)
    assert "Allowed steps are fluids_draft_mfl, case_publish\n  and run_execute" in off
    assert "__" not in off.replace("__init__", "")


# ------------------------------------------------- plans: generate, publish, run


@pytest.fixture
def real(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_on: None) -> SimpleNamespace:
    """A real durable transaction and publish journal; only the OLGA process is faked.

    The case links fluid.tab, which does not exist yet: the plan generates it first.
    """
    from case_spec_v2_support import FLUID_LABEL
    from test_case_publish_tool_integration import _spec as real_spec

    from olga_companion.case_transactions import case_spec_hash, plan_case_edits

    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setenv("OLGA_CASE_TRANSACTION_DIR", str(private / "transactions"))
    monkeypatch.setenv("OLGA_CASE_PUBLISH_JOURNAL_DIR", str(private / "journal"))
    generation = workspace.context_generation()
    spec = real_spec()
    plan = plan_case_edits(
        spec,
        [{"op": "set_integration", "end_time_s": 7200.0}],
        expected_hash=case_spec_hash(spec),
        workspace_root=root,
        context_generation=generation,
        pending_companion="fluid.tab",
    )
    assert plan.publishable is True, getattr(plan, "errors", plan)
    launch = SimpleNamespace(previews=[], launches=[])

    def preview(source: str, timeout_s: int = 3600, candidate_id: str | None = None) -> dict[str, Any]:
        launch.previews.append((Path(source).name, timeout_s))
        return {
            "source": source, "selection_id": "sel-real", "validation": {"valid": True},
            "timeout_s": timeout_s, "runtime_id": "olga-2025", "detection": {"exe": "OLGA-2025.exe"},
        }

    def execute(source: str, **kwargs: Any) -> dict[str, Any]:
        launch.launches.append((Path(source).name, kwargs))
        return {"run_id": "run0001", "state": "running"}

    monkeypatch.setattr(runner, "preview_run", preview)
    monkeypatch.setattr(runner, "execute_run", execute)
    publish = {
        "transaction_id": plan.transaction_id, "source_hash": plan.source_hash,
        "compiled_hash": plan.compiled_hash, "destination_rel": "chat-built.genkey",
        "context_generation": generation,
    }
    # The grid covers the case's 30-40 C boundaries, so the pre-run range check passes.
    table = _gen(fluid_label=FLUID_LABEL, tab_rel="fluid.tab", temperatures=[-10, 0, 10, 20, 30, 40, 50, 60])
    return SimpleNamespace(
        root=root, generation=generation, plan=plan, launch=launch, publish=publish, table=table
    )


def _steps(real: SimpleNamespace) -> list[dict[str, Any]]:
    return [
        {"kind": TOOL, "args": dict(real.table)},
        {"kind": "case_publish", "args": dict(real.publish)},
        {"kind": "run_execute", "args": {"timeout_s": 600}, "source_from_step": 2},
    ]


def _register(steps: list[dict[str, Any]], generation: int) -> tuple[str, str]:
    session_id = history.new_session("plan")
    pending_id = pending_approvals.register(
        action_kind="action_plan", args={"steps": steps}, call_id="plan-1",
        context_generation=generation, session_id=session_id,
    )
    return session_id, pending_id


def _execute(session_id: str, pending_id: str, generation: int) -> dict[str, Any]:
    return approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="plan-1", context_generation=generation
    )


def _states(body: dict[str, Any]) -> list[str]:
    return [step["state"] for step in body["result"]["steps"]]


def test_one_approval_generates_the_table_publishes_the_case_and_starts_the_run(real: SimpleNamespace) -> None:
    session_id, pending_id = _register(_steps(real), real.generation)

    body = _execute(session_id, pending_id, real.generation)

    assert _states(body) == ["done", "done", "done"]
    assert fluid_table.pickup_tab(str(real.root / "fluid.tab"), "TEST_FLUID")["valid"] is True
    published = real.root / "chat-built.genkey"
    assert hashlib.sha256(published.read_bytes()).hexdigest() == real.plan.compiled_hash
    assert real.launch.previews == [("chat-built.genkey", 600)]
    assert len(real.launch.launches) == 1
    assert body["result"]["steps"][0]["result"]["validator"]["valid"] is True


def test_the_plan_card_shows_the_table_step_the_publish_and_the_run(real: SimpleNamespace) -> None:
    shown = approval_display.build("action_plan", {"steps": _steps(real)}, locale="en")

    assert [row["kind"] for row in shown["plan"]["steps"]] == [TOOL, "case_publish", "run_execute"]
    assert shown["plan"]["steps"][2]["bound_to"] == 2


def test_a_table_that_appears_before_the_click_refuses_the_whole_plan_and_runs_nothing(
    real: SimpleNamespace,
) -> None:
    session_id, pending_id = _register(_steps(real), real.generation)
    (real.root / "fluid.tab").write_text("someone else's table\n", encoding="utf-8")

    body = _execute(session_id, pending_id, real.generation)

    assert body["state"] == "failed"
    assert not (real.root / "chat-built.genkey").exists()
    assert (real.root / "fluid.tab").read_text(encoding="utf-8") == "someone else's table\n"
    assert real.launch.launches == []


def test_a_table_that_appears_between_two_steps_fails_that_step_and_stops_the_chain(
    real: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = {**real.table, "fluid_label": "SECOND", "tab_rel": "second.tab"}
    steps = [{"kind": TOOL, "args": dict(real.table)}, {"kind": TOOL, "args": second}]
    session_id, pending_id = _register(steps, real.generation)
    real_dispatch = tools.dispatch

    def intruder(name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = real_dispatch(name, args)
        (real.root / "second.tab").write_text("someone else's table\n", encoding="utf-8")
        return result

    monkeypatch.setattr(tools, "dispatch", intruder)

    body = _execute(session_id, pending_id, real.generation)

    assert _states(body) == ["done", "failed"]
    assert "already exists" in body["result"]["steps"][1]["error"]
    assert (real.root / "second.tab").read_text(encoding="utf-8") == "someone else's table\n"


def test_a_publish_with_a_missing_table_is_refused_without_a_table_step(real: SimpleNamespace) -> None:
    steps = _steps(real)[1:]
    steps[1]["source_from_step"] = 1
    with pytest.raises(ToolError, match="companion"):
        tools.approval_payload("action_plan", {"steps": steps})


def test_a_publish_is_refused_when_the_generated_table_sits_elsewhere(real: SimpleNamespace) -> None:
    (real.root / "sub").mkdir()
    steps = _steps(real)
    steps[0]["args"] = {**steps[0]["args"], "tab_rel": "sub/fluid.tab"}
    with pytest.raises(ToolError, match="companion"):
        tools.approval_payload("action_plan", {"steps": steps})


def test_a_publish_is_refused_when_the_generated_label_differs_from_the_case(real: SimpleNamespace) -> None:
    steps = _steps(real)
    steps[0]["args"] = {**steps[0]["args"], "fluid_label": "OTHER_FLUID"}
    with pytest.raises(ToolError, match="companion"):
        tools.approval_payload("action_plan", {"steps": steps})


def test_a_table_step_after_the_publish_does_not_excuse_a_missing_table(real: SimpleNamespace) -> None:
    steps = _steps(real)
    steps[0], steps[1] = steps[1], steps[0]
    steps[2]["source_from_step"] = 1
    with pytest.raises(ToolError, match="companion"):
        tools.approval_payload("action_plan", {"steps": steps})


def test_a_standalone_publish_still_needs_its_table_on_disk(real: SimpleNamespace) -> None:
    with pytest.raises(ToolError, match="companion"):
        tools.approval_payload("case_publish", dict(real.publish))


def test_the_publish_is_refused_at_its_turn_if_the_generated_label_is_wrong(
    real: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id, pending_id = _register(_steps(real), real.generation)
    real_dispatch = tools.dispatch

    def swap(name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = real_dispatch(name, args)
        if name == TOOL:
            text = (real.root / "fluid.tab").read_text(encoding="utf-8")
            (real.root / "fluid.tab").write_text(text.replace("TEST_FLUID", "WRONG_ONE"), encoding="utf-8")
        return result

    monkeypatch.setattr(tools, "dispatch", swap)

    body = _execute(session_id, pending_id, real.generation)

    assert _states(body) == ["done", "failed", "not_run"]
    assert not (real.root / "chat-built.genkey").exists()


# --------------------------------------------- case_edit_plan with a pending table


def _edit_args(real: SimpleNamespace, **extra: Any) -> dict[str, Any]:
    from test_case_publish_tool_integration import _spec as real_spec

    from olga_companion.case_transactions import case_spec_hash

    spec = real_spec()
    return {
        "spec": spec,
        "spec_hash": case_spec_hash(spec),
        "operations": [{"op": "set_integration", "end_time_s": 3600.0}],
        **extra,
    }


def test_case_edit_plan_accepts_a_table_that_a_plan_will_generate(real: SimpleNamespace) -> None:
    result = tools.dispatch("case_edit_plan", _edit_args(real, pending_table="fluid.tab"))
    assert result["publishable"] is True


def test_case_edit_plan_still_refuses_a_missing_table_without_the_argument(real: SimpleNamespace) -> None:
    with pytest.raises(ToolError, match="missing"):
        tools.dispatch("case_edit_plan", _edit_args(real))


def test_case_edit_plan_refuses_a_pending_table_that_is_not_the_one_the_case_links(real: SimpleNamespace) -> None:
    with pytest.raises(ToolError, match="missing"):
        tools.dispatch("case_edit_plan", _edit_args(real, pending_table="other.tab"))


def test_case_edit_plan_checks_an_existing_table_normally_even_when_pending(real: SimpleNamespace) -> None:
    (real.root / "fluid.tab").write_text('PVTTABLE LABEL = "NOT_THIS", PHASE = BOTH\n', encoding="utf-8")
    result = tools.dispatch("case_edit_plan", _edit_args(real, pending_table="fluid.tab"))
    assert result["publishable"] is False
    assert "label" in json.dumps(result["errors"]).casefold()


def test_case_edit_plan_refuses_a_pending_table_without_the_flag_even_when_called_directly(
    real: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion.agent import case_transaction_tools

    monkeypatch.delenv(FLAG, raising=False)
    with pytest.raises(ToolError, match="not available"):
        case_transaction_tools.edit_plan(_edit_args(real, pending_table="fluid.tab"), tools._path_bindings())


def test_case_edit_plan_has_no_pending_table_argument_without_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FLAG, raising=False)
    schema = tools.TOOLS["case_edit_plan"].parameters
    assert "pending_table" not in json.dumps(schema)


# ------------------------------------------- lntabfix M1: a refusal after the click


def _click_body(session_id: str, pending_id: str, generation: int, call_id: str = "g-1") -> dict[str, Any]:
    return {
        "pending_id": pending_id, "session_id": session_id,
        "call_id": call_id, "context_generation": generation,
    }


def test_a_standalone_engine_refusal_after_the_click_reads_as_failed_with_its_reason(
    native_on: None, root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user approves, the engine refuses a non-converging node: a definite failure, not 'uncertain'."""
    from fastapi.testclient import TestClient

    from olga_companion import native_tab, sidecar
    from olga_companion.pvt_engine.errors import PvtEngineError

    def no_convergence(*_a: Any, **_k: Any):
        raise PvtEngineError("Node P=1e6 Pa, T=300 K: the flash did not converge; nothing was written.")

    monkeypatch.setattr(native_tab, "generate_table", no_convergence)
    headers = {"X-Session-Token": session_token.boot_token()}
    session_id = history.new_session("gen")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args=_gen(), call_id="g-1", context_generation=gen, session_id=session_id
    )

    clicked = TestClient(sidecar.app).post(
        "/api/approvals/execute", json=_click_body(session_id, pending_id, gen), headers=headers
    )

    assert clicked.status_code == 200, clicked.text
    body = clicked.json()
    assert body["state"] == "failed"
    assert body["resume_allowed"] is False
    assert "did not converge" in body["result"]["error"]
    assert "could not be confirmed" not in json.dumps(body)
    assert sorted(path.name for path in root.iterdir()) == []


def test_an_arithmetic_engine_failure_before_write_is_refused_not_uncertain(
    native_on: None, root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ZeroDivision and Overflow before any write are a refusal, never an uncertain outcome."""
    from fastapi.testclient import TestClient

    from olga_companion import native_tab, sidecar

    def divide(*_a: Any, **_k: Any):
        raise ZeroDivisionError("grid step")

    monkeypatch.setattr(native_tab, "generate_table", divide)
    headers = {"X-Session-Token": session_token.boot_token()}
    session_id = history.new_session("gen")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args=_gen(), call_id="g-div", context_generation=gen, session_id=session_id
    )

    clicked = TestClient(sidecar.app).post(
        "/api/approvals/execute",
        json=_click_body(session_id, pending_id, gen, "g-div"),
        headers=headers,
    )

    assert clicked.status_code == 200, clicked.text
    body = clicked.json()
    assert body["state"] == "failed"
    assert "grid step" in body["result"]["error"]
    assert "uncertain" not in json.dumps(body)
    assert "could not be confirmed" not in json.dumps(body)
    assert sorted(path.name for path in root.iterdir()) == []


def test_a_standalone_refusal_fails_the_pending_approval_with_the_reason(
    native_on: None, root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import native_tab

    calls: list[int] = []

    def refuse(*_a: Any, **_k: Any):
        calls.append(1)
        raise native_tab.NativeTabError("Node P=1e6 Pa: the flash did not converge; nothing was written.")

    monkeypatch.setattr(native_tab, "generate", refuse)
    session_id = history.new_session("gen")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args=_gen(), call_id="g-1", context_generation=gen, session_id=session_id
    )

    body = approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="g-1", context_generation=gen
    )

    assert body["state"] == "failed" and body["resume_allowed"] is False
    assert "did not converge" in body["result"]["error"]
    with pytest.raises(Exception):
        approval_execution.execute(
            pending_id=pending_id, session_id=session_id, call_id="g-1", context_generation=gen
        )
    assert calls == [1], "the closed approval is never dispatched a second time"


def test_a_standalone_run_refusal_before_launch_reads_as_failed_with_the_real_reason(
    root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import genkey_static

    (root / "old.genkey").write_text("CASE LABEL=old\nENDCASE\n", encoding="utf-8")

    def refuse(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise genkey_static.OlgaInputError(
            "Validation reported blocking errors. Fix the case or set override=true to run anyway."
        )

    monkeypatch.setattr(runner, "execute_run", refuse)
    session_id = history.new_session("run")
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": "old.genkey", "selection_id": "sel-9", "timeout_s": 60},
        call_id="r-1", context_generation=gen, session_id=session_id,
    )

    body = approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="r-1", context_generation=gen
    )

    assert body["state"] == "failed" and body["resume_allowed"] is False
    assert "blocking errors" in body["result"]["error"]
    assert "could not be confirmed" not in json.dumps(body)


def test_an_untyped_tool_error_on_a_standalone_card_is_still_uncertain(
    native_on: None, root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def vague(*_a: Any, **_k: Any):
        raise ToolError("something happened after the step began")

    monkeypatch.setattr(tools, "dispatch", vague)
    session_id = history.new_session("gen")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args=_gen(), call_id="g-1", context_generation=gen, session_id=session_id
    )

    with pytest.raises(approval_execution.ApprovalDispatchUncertainError):
        approval_execution.execute(
            pending_id=pending_id, session_id=session_id, call_id="g-1", context_generation=gen
        )


# ------------------------- lntabfix 3, 4, 10, 11: validator rejection, race, grid cap


def test_a_standalone_validator_rejection_reads_as_failed_and_names_the_kept_file(
    native_on: None, root: Path, gen: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reject_every_table(monkeypatch)
    session_id = history.new_session("gen")
    pending_id = pending_approvals.register(
        action_kind=TOOL, args=_gen(), call_id="g-1", context_generation=gen, session_id=session_id
    )

    body = approval_execution.execute(
        pending_id=pending_id, session_id=session_id, call_id="g-1", context_generation=gen
    )

    assert body["state"] == "failed" and body["resume_allowed"] is False
    assert "syn_co2.tab" in body["result"]["error"]
    assert (root / "syn_co2.tab").is_file()


def test_a_plan_row_for_a_rejected_table_names_the_kept_file_and_never_says_refused_before_it_started(
    real: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reject_every_table(monkeypatch)
    session_id, pending_id = _register(_steps(real), real.generation)

    body = _execute(session_id, pending_id, real.generation)

    assert _states(body) == ["failed", "not_run", "not_run"]
    row = body["result"]["steps"][0]
    assert "fluid.tab" in row["error"]
    assert "do not link" in row["error"].casefold()
    assert "before it started" not in row["error"]
    assert row["code"] == "table_rejected"
    assert (real.root / "fluid.tab").is_file(), "the file stays for inspection"
    assert not (real.root / "chat-built.genkey").exists()


@pytest.mark.parametrize(
    "text",
    [
        "Property ROG: 5000 kg/m3 is above the limit",
        "RS must stay in kg/kg and CPG in J/kg/C",
        "DROGDP is in s2/m2; VISG in Ns/m2.",
    ],
)
def test_a_reason_with_unit_slashes_is_shown_not_replaced_by_the_fallback(text: str) -> None:
    from olga_companion.agent import plan_execution

    assert plan_execution._reason(text, "invalid_step") == text


@pytest.mark.parametrize(
    "text",
    [
        "cannot read /home/someone/work/case.genkey",
        "cannot read C:\\Users\\someone\\case.genkey",
        "cannot read sub/fluid.tab",
        "cannot read kg/m3/other/dir/file.tab",
        "cannot read ./kg/m3",
    ],
)
def test_a_reason_that_carries_a_path_still_falls_back(text: str) -> None:
    from olga_companion.agent import plan_execution

    assert plan_execution._reason(text, "invalid_step") == plan_execution._FALLBACK["invalid_step"]


def test_the_plan_runner_has_no_second_table_precheck() -> None:
    from olga_companion.agent import plan_execution

    assert not hasattr(plan_execution, "_check_table")


def test_a_table_that_appears_after_the_step_is_minted_fails_the_step_and_is_not_uncertain(
    real: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrow window between the payload check and the write: nothing was written, so it is a failure."""
    session_id, pending_id = _register(_steps(real), real.generation)
    real_mint = approvals.mint

    def mint_then_intrude(kind: str, payload: Any, **kwargs: Any) -> dict[str, Any]:
        minted = real_mint(kind, payload, **kwargs)
        if kind == TOOL:
            (real.root / "fluid.tab").write_text("someone else's table\n", encoding="utf-8")
        return minted

    monkeypatch.setattr(approvals, "mint", mint_then_intrude)

    body = _execute(session_id, pending_id, real.generation)

    assert body["state"] != "uncertain"
    assert _states(body) == ["failed", "not_run", "not_run"]
    assert "already exists" in body["result"]["steps"][0]["error"]
    assert (real.root / "fluid.tab").read_text(encoding="utf-8") == "someone else's table\n"
    assert real.launch.launches == []


def _grid(side: int) -> dict[str, Any]:
    return {
        "temperatures": [-10 + index for index in range(side)],
        "pressures": [10 + index for index in range(side)],
    }


def test_the_node_cap_is_a_product_limit_far_inside_the_plan_lifetime() -> None:
    from olga_companion import native_tab
    from olga_companion.agent import plan_model

    assert 100 <= native_tab.MAX_GRID_NODES <= 5000
    # 9 ms per node was the slowest measured flash (eight components); ten times that is still short.
    assert native_tab.MAX_GRID_NODES * 0.09 < plan_model.PLAN_TTL_SECONDS / 4


def test_a_grid_at_the_node_cap_is_accepted_and_one_node_over_is_refused_without_a_card(
    native_on: None, root: Path
) -> None:
    import math

    from olga_companion import native_tab

    side = math.isqrt(native_tab.MAX_GRID_NODES)
    assert side * side == native_tab.MAX_GRID_NODES, "the product limit is a square grid"
    tools.approval_payload(TOOL, _gen(**_grid(side)))

    with pytest.raises(ToolError, match=str(native_tab.MAX_GRID_NODES)) as caught:
        tools.approval_payload(TOOL, _gen(**_grid(side + 1)))
    assert "nodes" in str(caught.value)
    assert sorted(path.name for path in root.iterdir()) == []


def test_a_plan_with_a_grid_over_the_cap_is_refused_before_any_card(native_on: None, root: Path) -> None:
    import math

    from olga_companion import native_tab

    big = _gen(**_grid(math.isqrt(native_tab.MAX_GRID_NODES) + 1))
    with pytest.raises(ToolError, match="nodes"):
        tools.approval_payload("action_plan", {"steps": [{"kind": TOOL, "args": big}]})


def test_the_tool_description_states_the_node_cap(native_on: None) -> None:
    from olga_companion import native_tab

    assert str(native_tab.MAX_GRID_NODES) in tools.TOOLS[TOOL].description


# ------------------------------------------------ lntabfix 9: prompt and tool wording

# sha256 of the release system-prompt template (placeholders still in place) before the table generator existed.
# lnlow #5 added the plain-words rule for tool/field names, so the pinned bytes moved here (strength unchanged: still byte-identical).
# The run time-limit rule (7-day ceiling, ask before a long run) moved them again (strength unchanged).
# Start states, the parallel-flowpath loop, labelled value proposals and the starter air-water table moved them again (strength unchanged).
# The Y-up sentence (y is the vertical axis of a centerline_m point) moved them again (strength unchanged).
# The mass-fraction rule and the user's-value-wins rule moved them again (strength unchanged).
# The read-both-ends pressure-drop rule and the volume-basis conversion rule moved them again (strength unchanged).
# The six-decimal tool-number rounding rule moved them again (strength unchanged).
# The valve-schedule sentence (hyper-real round 6) moved them again (strength unchanged).
# The LIQC/HOL output-placement sentence (hyper-real round 8) moved them again (strength unchanged).
# Rehashed for the product-name change only (earlier working name -> OLGA Companion); no other byte differs.
RELEASE_PROMPT_TEMPLATE_SHA256 = "469ebddf963c9f0477abb6c1ef22abf069fca2f6c08880e9870420f7e3d1977d"


def test_the_release_prompt_is_byte_identical_to_the_text_before_the_generator() -> None:
    off = runtime.build_system_prompt(native_tab=False)
    template = off.replace(runtime.DESTINATION_RULE, "__DESTINATION_RULE__").replace(
        ", ".join(runtime.SUPPORTED_MODELS), "__FLUID_MODELS__"
    )
    assert hashlib.sha256(template.encode("utf-8")).hexdigest() == RELEASE_PROMPT_TEMPLATE_SHA256


def test_the_compare_offer_is_in_the_prompt_only_with_the_flag(native_on: None) -> None:
    assert "fluids_compare_tab" not in runtime.build_system_prompt(native_tab=False)
    on = runtime.build_system_prompt(native_tab=True)
    assert "fluids_compare_tab" in on
    assert on.index("fluids_compare_tab") > on.index(TOOL)


def test_the_compare_tool_description_is_neutral() -> None:
    spec = next(item for item in tools.tool_specs() if item["name"] == "fluids_compare_tab")
    text = spec["description"].casefold()
    assert "two .tab files" in text
    for word in ("multiflash", "owner", "engine", "app "):
        assert word not in text
