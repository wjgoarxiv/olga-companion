"""A chat turn run by the local CLI gets its own short-lived bridge secret, kept only in memory.

Read tools answer under that turn's workspace and language. A side-effect tool never runs and
never becomes a card from the bridge: the app's own chat loop asks for approval instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olga_companion import bridge_registry, sidecar_bridge_routes, starter_fluids, workspace
from olga_companion.agent import history, pending_approvals
from olga_companion.sidecar import app

FIXTURES = Path(__file__).parent / "fixtures" / "fluids"


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "workspace"
    root.mkdir()
    fluids = tmp_path / "bundle"
    fluids.mkdir()
    stand_in = (FIXTURES / "standard_three.tab").read_text(encoding="utf-8").replace("FLUID-A", "AIR_WATER")
    (fluids / starter_fluids.TABLE_NAME).write_text(stand_in, encoding="utf-8")
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(root))
    monkeypatch.setattr(starter_fluids, "bundled_table", lambda: fluids / starter_fluids.TABLE_NAME)
    monkeypatch.setattr(bridge_registry, "_path", lambda: tmp_path / "bridge-connections.json")
    pending_approvals.revoke_all()
    bridge_registry.revoke_all_chat_turns()
    yield root
    bridge_registry.revoke_all_chat_turns()
    pending_approvals.revoke_all()


def _client() -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8865", client=("127.0.0.1", 50000))


def _turn(locale: str = "en") -> str:
    return bridge_registry.issue_chat_turn("chat-1", workspace.context_generation(), locale, ttl=60)


def _call(secret: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = _client().post("/api/bridge/call", json={"name": name, "arguments": arguments},
                              headers={"X-Bridge-Secret": secret})
    assert response.status_code == 200, response.text
    return response.json()


def _data(result: dict[str, Any]) -> Any:
    text = result["content"][0]["text"]
    return json.loads(text[len(sidecar_bridge_routes.DATA_OPEN): -len(sidecar_bridge_routes.DATA_CLOSE)])


def test_a_read_tool_answers_as_fenced_data():
    result = _call(_turn(), "olga_glossary", {"term": "ENDTIME"})
    assert result["isError"] is False
    assert result["content"][0]["text"].startswith(sidecar_bridge_routes.DATA_OPEN)
    assert _data(result)


def test_the_tool_list_is_the_same_as_for_connected_tools():
    listed = _client().get("/api/bridge/tools", headers={"X-Bridge-Secret": _turn()}).json()["tools"]
    assert [t["name"] for t in listed] == [t["name"] for t in sidecar_bridge_routes.tool_list()]


def test_a_side_effect_tool_leaves_no_card_and_no_file(_isolated: Path):
    sessions_before = [s.id for s in history.list_sessions()]
    result = _call(_turn(), "fluids_starter_tab", {"tab_rel": "air_water.tab"})
    assert result["isError"] is True
    assert not (_isolated / "air_water.tab").exists()
    assert pending_approvals.revoke_all() == 0
    assert [s.id for s in history.list_sessions()] == sessions_before
    assert not Path(bridge_registry._path()).exists()


def test_after_a_side_effect_ask_the_turn_is_halted():
    secret = _turn()
    _call(secret, "fluids_starter_tab", {"tab_rel": "air_water.tab"})
    assert _call(secret, "olga_glossary", {"term": "ENDTIME"})["isError"] is True


def test_a_halted_turn_refuses_reads():
    secret = _turn()
    bridge_registry.halt_chat_turn(secret)
    assert _call(secret, "olga_glossary", {"term": "ENDTIME"})["isError"] is True


@pytest.mark.parametrize("forged", ["approval_token", "pending_id", "approved"])
def test_a_forged_approval_field_is_refused(forged):
    result = _call(_turn(), "olga_glossary", {"term": "ENDTIME", forged: "x"})
    assert result["isError"] is True and forged in _data(result)["error"]


def test_the_status_tool_is_not_offered_to_a_chat_turn():
    result = _call(_turn(), "approval_status", {"pending_id": "x"})
    assert result["isError"] is True


def test_revoke_gives_401():
    secret = _turn()
    bridge_registry.revoke_chat_turn(secret)
    response = _client().post("/api/bridge/call", json={"name": "olga_glossary", "arguments": {}},
                              headers={"X-Bridge-Secret": secret})
    assert response.status_code == 401


def test_an_expired_turn_gives_401(monkeypatch):
    secret = bridge_registry.issue_chat_turn("chat-1", workspace.context_generation(), "en", ttl=60)
    clock = bridge_registry._now() + 120
    monkeypatch.setattr(bridge_registry, "_now", lambda: clock)
    response = _client().get("/api/bridge/tools", headers={"X-Bridge-Secret": secret})
    assert response.status_code == 401


def test_a_workspace_switch_mid_turn_gives_the_stale_error():
    secret = bridge_registry.issue_chat_turn("chat-1", workspace.context_generation() + 1, "en", ttl=60)
    result = _call(secret, "olga_glossary", {"term": "ENDTIME"})
    assert result["isError"] is True and "workspace changed" in _data(result)["error"]


def test_the_chat_secret_is_never_written_to_disk(tmp_path):
    secret = _turn()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret not in path.read_text(encoding="utf-8", errors="ignore")
    assert "claude_cli" not in bridge_registry.PRODUCTS


def test_the_product_secret_still_works_beside_a_chat_turn():
    _turn()
    product_secret = bridge_registry.issue("claude-code")
    assert _call(product_secret, "olga_glossary", {"term": "ENDTIME"})["isError"] is False


def test_the_turn_language_reaches_the_tool(monkeypatch):
    seen = {}
    from olga_companion.agent import tool_locale, tools

    def fake_dispatch(_name, _args):
        seen["locale"] = tool_locale.current()
        return {"ok": True}

    monkeypatch.setattr(tools, "dispatch", fake_dispatch)
    _call(_turn("ko"), "olga_glossary", {"term": "ENDTIME"})
    assert seen["locale"] == "ko"


def test_a_continuation_turn_does_not_fill_in_the_case_selected_now(monkeypatch):
    from olga_companion.agent import tools

    filled = []
    real = tools.apply_active_default

    def spy(name, args):
        filled.append(name)
        return real(name, args)

    monkeypatch.setattr(tools, "apply_active_default", spy)
    plain = bridge_registry.issue_chat_turn("chat-1", workspace.context_generation(), "en", ttl=60)
    _call(plain, "olga_glossary", {"term": "ENDTIME"})
    assert filled == ["olga_glossary"]
    filled.clear()
    resumed = bridge_registry.issue_chat_turn("chat-1", workspace.context_generation(), "en", ttl=60,
                                              fill_active_case=False)
    answer = _call(resumed, "olga_glossary", {"term": "ENDTIME"})
    assert filled == [] and answer["isError"] is False
