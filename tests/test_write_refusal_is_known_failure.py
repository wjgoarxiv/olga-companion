"""A file-write approval refused before anything is written ends as a known failure.

Bug report 2026-11-13 (0.1.4, enterprise PC): pressing "승인하고 파일 쓰기" showed
"승인 결과가 확인되지 않았습니다" and the chat could not go on. fluids_draft_mfl and
genkey_save raised plain errors for refusals such as an existing destination or a
missing folder, which the approval path must treat as an uncertain dispatch. The
card dead-ended and the model was told only that the outcome was unknown.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import fluid_table, genkey_static, workspace
from olga_companion.agent import history, pending_approvals, session_token, tool_side_effects, tools
import olga_companion.sidecar as sidecar


def _mfl_target(tmp_path: Path, mfl_rel: str) -> dict[str, Any]:
    return {
        "mfl_rel": mfl_rel,
        "tab_rel": "air_water.tab",
        "tab_abs": str(tmp_path / "air_water.tab"),
        "fluid_label": "AIR_WATER",
        "components": [{"name": "WATER", "mole_fraction": 1.0}],
        "model": "CPA",
        "temperatures": [0.0, 25.0],
        "temperature_unit": "degC",
        "pressures": [1.0, 30.0],
        "pressure_unit": "bar",
        "hawater": False,
    }


@pytest.fixture
def _no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tool_side_effects, "_consume", lambda *_a: None)
    monkeypatch.setattr(tool_side_effects.workspace, "contained", lambda rel: tmp_path / rel)
    monkeypatch.setattr(fluid_table, "build_mfl_text", lambda **_k: "remove all;")


def test_existing_mfl_destination_is_a_refusal(tmp_path: Path, _no_token: None) -> None:
    (tmp_path / "air_water.mfl").write_text("kept", encoding="utf-8")

    with pytest.raises(tools.ToolRefusedError, match="already exists"):
        tool_side_effects.fluids_draft_mfl({}, lambda *_a: _mfl_target(tmp_path, "air_water.mfl"))

    assert (tmp_path / "air_water.mfl").read_text(encoding="utf-8") == "kept"


def test_missing_mfl_folder_is_a_refusal(tmp_path: Path, _no_token: None) -> None:
    with pytest.raises(tools.ToolRefusedError, match="folder does not exist"):
        tool_side_effects.fluids_draft_mfl({}, lambda *_a: _mfl_target(tmp_path, "nope/air_water.mfl"))


def test_mfl_write_blocked_by_the_os_is_a_refusal(
    tmp_path: Path, _no_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(_path: str, _text: str) -> dict[str, Any]:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(fluid_table, "write_draft_mfl", blocked)

    with pytest.raises(tools.ToolRefusedError, match="Access is denied"):
        tool_side_effects.fluids_draft_mfl({}, lambda *_a: _mfl_target(tmp_path, "air_water.mfl"))


def test_genkey_save_refusals_are_known(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_side_effects, "_consume", lambda *_a: None)
    monkeypatch.setattr(tool_side_effects.workspace, "contained", lambda rel: tmp_path / rel)
    ran: list[str] = []
    monkeypatch.setattr(genkey_static, "run_tool", lambda *a, **_k: ran.append(a[0]))

    def target(save_rel: str, topology: str = "simple_pipeline") -> Any:
        return lambda *_a: {"save_rel": save_rel, "topology": topology, "endtime_s": 3600, "pvtfile": "./fluid.tab"}

    with pytest.raises(tools.ToolRefusedError, match="folder does not exist"):
        tool_side_effects.genkey_save({}, target("missing/new.genkey", sorted(genkey_static.ALLOWED_TOPOLOGIES)[0]))
    with pytest.raises(tools.ToolRefusedError, match="Unknown topology"):
        tool_side_effects.genkey_save({}, target("new.genkey", "not-a-topology"))
    assert ran == []


def test_multiflash_that_never_started_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_side_effects, "_consume", lambda *_a: None)
    target = lambda *_a: {"mfl_path": "x.mfl"}  # noqa: E731
    monkeypatch.setattr(fluid_table, "find_multiflash", lambda: {"found": False, "message": "Multiflash is not installed."})
    with pytest.raises(tools.ToolRefusedError, match="not installed"):
        tool_side_effects.multiflash_open({}, target)

    def no_start(_exe: str, _mfl: str | None = None) -> dict[str, Any]:
        raise fluid_table.FluidTableError("Multiflash did not start: mf.exe")

    monkeypatch.setattr(fluid_table, "find_multiflash", lambda: {"found": True, "exe": "mf.exe"})
    monkeypatch.setattr(fluid_table, "launch_multiflash", no_start)
    with pytest.raises(tools.ToolRefusedError, match="did not start"):
        tool_side_effects.multiflash_open({}, target)


def test_refused_write_click_returns_failed_with_reason_and_tells_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    pending_approvals.revoke_all()
    (tmp_path / "air_water.mfl").write_text("kept", encoding="utf-8")
    monkeypatch.setattr(tools, "approval_payload", lambda _kind, _args: {"mfl_rel": "air_water.mfl"})
    monkeypatch.setattr(tool_side_effects, "_consume", lambda *_a: None)
    monkeypatch.setattr(fluid_table, "build_mfl_text", lambda **_k: "remove all;")
    monkeypatch.setattr(
        tools.TOOLS["fluids_draft_mfl"],
        "handler",
        lambda args: tool_side_effects.fluids_draft_mfl(args, lambda *_a: _mfl_target(tmp_path, "air_water.mfl")),
    )
    monkeypatch.setattr(tools._validation, "validate_tool_arguments", lambda *_a: None)
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    headers = {"X-Session-Token": session_token.boot_token()}
    session_id = str(api.post("/api/chat/session", json={"title": ""}, headers=headers).json()["session_id"])
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="fluids_draft_mfl",
        args={"mfl_rel": "air_water.mfl"},
        call_id="call-mfl",
        context_generation=generation,
        session_id=session_id,
    )
    payload = {"pending_id": pending_id, "session_id": session_id, "call_id": "call-mfl", "context_generation": generation}

    try:
        response = api.post("/api/approvals/execute", json=payload, headers=headers)
    finally:
        pending_approvals.revoke_all()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "failed"
    assert "already exists" in str(body["result"])
    answers = [
        record for record in history.read(session_id)
        if record.get("type") == "tool_result" and record.get("call_id") == "call-mfl"
    ]
    assert answers and "already exists" in str(answers[-1]["result"])
