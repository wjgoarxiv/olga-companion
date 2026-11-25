"""fluids_make_tab: the installed Multiflash engine makes a .tab from an .mfl after one approval.

Offline: the engine child is replaced by a fake that writes a small stored table.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from olga_companion import fluid_provenance, fluid_table, headless_mcp, multiflash_direct, workspace
from olga_companion.agent import approval_display, approvals, pending_approvals, plan_model, session_token, tools
from olga_companion.agent.tool_validation import ToolError, ToolFailedError, ToolRefusedError

TOOL = "fluids_make_tab"
FIX = Path(__file__).parent / "fixtures" / "multiflash"
ARGS = {"source_rel": "gas_water.mfl", "tab_rel": "gas_water.tab"}


def _engine(request: dict[str, Any]) -> dict[str, Any]:
    table = (FIX / "handwritten_3x3.tab").read_text(encoding="utf-8")
    Path(request["tab_path"]).write_text(table.replace("LABEL = probe", f"LABEL = {request['title']}", 1), encoding="utf-8")
    return {"ok": True, "errors": []}


@pytest.fixture(autouse=True)
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "gas_water.mfl").write_bytes((FIX / "gas_water.mfl").read_bytes())
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("OLGA_APP_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(fluid_table, "find_multiflash", lambda: {"found": True, "exe": str(tmp_path / "mf" / "MFBJ01.exe")})
    monkeypatch.setattr(fluid_table, "multiflash_path", lambda value: value)
    monkeypatch.setattr(multiflash_direct, "engine_available", lambda: None)
    monkeypatch.setattr(multiflash_direct, "run_engine", _engine)
    session_token.boot_token()
    pending_approvals.revoke_all()
    yield ws
    pending_approvals.revoke_all()


def _approved(args: dict[str, Any]) -> dict[str, Any]:
    payload = tools.approval_payload(TOOL, args)
    token = approvals.mint(TOOL, payload, context_generation=workspace.context_generation())["token"]
    return {**args, "approval_token": token, "idempotency_key": "k" * 32}


def test_it_is_a_closed_approval_gated_writer_that_never_joins_a_plan() -> None:
    tool = tools.TOOLS[TOOL]
    assert tool.side_effect is True
    assert set(tool.parameters["properties"]) == {"source_rel", "tab_rel", "approval_token", "idempotency_key"}
    assert set(tool.parameters["required"]) == {"source_rel", "tab_rel", "approval_token", "idempotency_key"}
    assert TOOL in plan_model.NEVER_IN_PLAN


def test_the_plugin_offers_it_and_asks_first() -> None:
    entry = next(t for t in headless_mcp.tool_list() if t["name"] == TOOL)
    assert entry["_meta"] == {"anthropic/requiresUserInteraction": True}
    assert entry["annotations"]["readOnlyHint"] is False


def test_an_approved_call_writes_a_new_valid_table_and_its_record(root: Path) -> None:
    result = tools.dispatch(TOOL, _approved(ARGS))
    assert result["ok"] is True
    assert result["tab_rel"] == "gas_water.tab"
    assert result["fluid_label"] == "GASWATER"
    assert result["validator"]["valid"] is True
    assert fluid_table.pickup_tab(str(root / "gas_water.tab"), "GASWATER")["valid"] is True
    assert fluid_provenance.record_path(root / "gas_water.tab").is_file()
    assert not [p.name for p in root.iterdir() if p.name.startswith(".")]
    assert str(root) not in json.dumps(result)


def test_the_plugin_call_writes_it_too(root: Path) -> None:
    reply = headless_mcp.call(TOOL, dict(ARGS))
    assert reply["isError"] is False, reply
    assert (root / "gas_water.tab").is_file()


@pytest.mark.parametrize("name", ["gas_water.tab", "gas_water.tab.made-from.json"])
def test_an_existing_table_or_record_is_refused_and_untouched(root: Path, name: str) -> None:
    (root / name).write_text("mine", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        tools.approval_payload(TOOL, ARGS)
    assert (root / name).read_text(encoding="utf-8") == "mine"
    assert headless_mcp.call(TOOL, dict(ARGS))["isError"] is True


@pytest.mark.parametrize(
    ("args", "why"),
    [
        ({**ARGS, "source_rel": ""}, "source_rel"),
        ({**ARGS, "tab_rel": ""}, "tab_rel"),
        ({**ARGS, "source_rel": "absent.mfl"}, "absent.mfl"),
        ({**ARGS, "source_rel": "../gas_water.mfl"}, "workspace"),
        ({**ARGS, "tab_rel": "../gas_water.tab"}, "workspace"),
        ({**ARGS, "tab_rel": "gas_water.txt"}, ".tab"),
        ({**ARGS, "tab_rel": "other/gas_water.tab"}, "same folder"),
    ],
)
def test_a_bad_request_is_refused_before_any_card(root: Path, args: dict[str, Any], why: str) -> None:
    (root / "other").mkdir()
    with pytest.raises(ToolError, match=why):
        tools.approval_payload(TOOL, args)
    assert not list(root.rglob("*.tab"))


def test_a_pc_without_the_engine_is_refused_before_any_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(multiflash_direct, "engine_available", lambda: "Multiflash was not found on this PC.")
    with pytest.raises(ToolError, match="not found"):
        tools.approval_payload(TOOL, ARGS)


def test_an_mfl_that_changed_after_the_card_writes_nothing(root: Path) -> None:
    approved = _approved(ARGS)
    (root / "gas_water.mfl").write_text((root / "gas_water.mfl").read_text() + "\n# edited #\n")
    with pytest.raises(ToolError):
        tools.dispatch(TOOL, approved)
    assert not (root / "gas_water.tab").exists()


def test_an_mfl_that_changes_while_the_engine_reads_is_not_built(root: Path) -> None:
    with pytest.raises(fluid_table.FluidTableError, match="changed"):
        multiflash_direct.make_tab(str(root / "gas_water.mfl"), "x.tab", expected_sha256="0" * 64)
    assert not (root / "x.tab").exists()


def test_an_engine_failure_is_reported_and_leaves_nothing(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(multiflash_direct, "run_engine", lambda request: {"ok": False, "errors": [20575]})
    with pytest.raises(ToolFailedError, match="20575"):
        tools.dispatch(TOOL, _approved(ARGS))
    assert sorted(p.name for p in root.iterdir()) == ["gas_water.mfl"]


def test_without_an_approval_nothing_runs(root: Path) -> None:
    with pytest.raises((ToolError, ToolRefusedError)):
        tools.dispatch(TOOL, dict(ARGS))
    assert not (root / "gas_water.tab").exists()


def test_the_payload_pins_the_source_and_the_grid(root: Path) -> None:
    payload = tools.approval_payload(TOOL, ARGS)
    assert payload["mfl_sha256"] == hashlib.sha256((root / "gas_water.mfl").read_bytes()).hexdigest()
    assert payload["fluid_label"] == "GASWATER"
    assert payload["grid_source"] == "mfl"


@pytest.mark.parametrize("locale", ["en", "ko"])
def test_the_card_names_the_files_and_the_grid(locale: str) -> None:
    rows = {r["key"]: r for r in approval_display.build(TOOL, ARGS, locale=locale)["fields"]}
    assert rows["file"]["value"] == "gas_water.tab"
    assert rows["mfl_file"]["value"] == "gas_water.mfl"
    assert rows["label"]["value"] == "GASWATER"
    assert rows["pressure_points"]["value"] == "3"
    assert rows["temperature_points"]["value"] == "3"
    assert rows["pressure_range"]["unit"] == "bar"
    assert rows["temperature_range"]["unit"] == "degC"
    assert "Multiflash" in rows["table_kind"]["value"]


def test_engine_available_says_why_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(fluid_table, "find_multiflash", lambda: {"found": False, "message": "no engine here"})
    assert multiflash_direct.engine_available() == "no engine here"
    monkeypatch.setattr(fluid_table, "find_multiflash", lambda: {"found": True, "exe": "x"})
    monkeypatch.setattr(multiflash_direct.os, "name", "posix")
    monkeypatch.delenv(multiflash_direct.WINDOWS_PYTHON_ENV, raising=False)
    assert "Windows" in (multiflash_direct.engine_available() or "")


def test_an_engine_warning_reaches_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(multiflash_direct, "run_engine", lambda request: {**_engine(request), "ok": False, "errors": [-20573]})
    result = tools.dispatch(TOOL, _approved(ARGS))
    assert result["ok"] is True
    assert "-20573" in result["engine_warnings"][0]


def test_a_large_table_with_many_warnings_still_validates(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """A real 62 x 50 three-phase table makes more than 8 MiB of validator warnings."""
    from olga_companion import fluids

    seen: dict[str, Any] = {}
    real = fluids.run_tool

    def spy(*args: Any, **kwargs: Any):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(fluids, "run_tool", spy)
    (root / "t.tab").write_bytes((FIX / "handwritten_3x3.tab").read_bytes())
    fluids._validate_tab(root / "t.tab")
    assert seen["max_output_bytes"] >= 32 * 1024 * 1024


def test_the_card_and_answer_say_when_the_high_accuracy_water_model_is_on(root: Path) -> None:
    keys = [r["key"] for r in approval_display.build(TOOL, ARGS, locale="en")["fields"]]
    assert "water_option" not in keys
    text = (root / "gas_water.mfl").read_text(encoding="utf-8")
    import re

    (root / "gas_water.mfl").write_text(re.sub(r'(table\s+olga\s+"[^"]*")', r"\1 HAWATER", text, flags=re.IGNORECASE), encoding="utf-8")
    rows = {r["key"]: r for r in approval_display.build(TOOL, ARGS, locale="en")["fields"]}
    assert rows["water_option"]["value"] == "HAWATER"
    assert tools.dispatch(TOOL, _approved(ARGS))["hawater"] is True


@pytest.mark.parametrize("name", ["가스.tab", "gas (1).tab", "gas+water.tab", "gas#1.tab"])
def test_a_name_the_engine_step_would_refuse_never_gets_a_card(name: str) -> None:
    with pytest.raises(ToolError, match="plain file name"):
        tools.approval_payload(TOOL, {**ARGS, "tab_rel": name})


def test_the_card_calls_the_source_a_multiflash_file() -> None:
    keys = [r["key"] for r in approval_display.build(TOOL, ARGS, locale="en")["fields"]]
    assert "mfl_file" in keys and "source_file" not in keys
