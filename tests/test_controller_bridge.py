"""0.1.21 F2: a PID loop edit asked for by an outside AI tool waits for the app's approval like any write."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_case_edit_routes import _rows, ws  # noqa: F401
from test_controller_edit_table import _loop_case
from test_mcp_bridge import _call, _client, _data, _post_via

from olga_companion import bridge_registry
from olga_companion.agent import pending_approvals

GAIN = {"op": "set_controller_value", "label": "PC", "gain": 0.8}
COPY = "loop_case.bridge.genkey"


@pytest.fixture(autouse=True)
def _bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bridge_registry, "_path", lambda: tmp_path / "bridge-connections.json")
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def test_a_loop_edit_from_an_outside_tool_writes_nothing_until_the_app_click(ws: Path) -> None:  # noqa: F811
    case = _loop_case(ws)
    before = case.read_bytes()
    rows = _rows(case)
    post = _post_via(_client(), bridge_registry.issue("codex"))

    plan = _data(_call(post, "case_edit_plan", {"source": rows["source"], "source_hash": rows["source_hash"], "destination_rel": COPY, "operations": [GAIN]}))
    assert plan["publishable"] is True, plan
    assert plan["semantic_diff"][0]["path"] == "controllers.PC.gain"

    publish = {**{key: plan[key] for key in ("transaction_id", "source_hash", "compiled_hash", "context_generation")}, "destination_rel": COPY}
    asked = _data(_call(post, "case_publish", publish))
    assert asked["state"] == "pending"
    assert not (ws / COPY).exists()
    assert case.read_bytes() == before


def test_an_outside_tool_cannot_send_an_approval_with_a_loop_edit(ws: Path) -> None:  # noqa: F811
    case = _loop_case(ws)
    rows = _rows(case)
    post = _post_via(_client(), bridge_registry.issue("gemini"))
    plan = _data(_call(post, "case_edit_plan", {"source": rows["source"], "source_hash": rows["source_hash"], "destination_rel": COPY, "operations": [GAIN]}))
    forged = {
        **{key: plan[key] for key in ("transaction_id", "source_hash", "compiled_hash", "context_generation")},
        "destination_rel": COPY,
        "approval_token": "x",
        "idempotency_key": "y",
    }
    result = _call(post, "case_publish", forged)
    assert result["isError"] is True
    assert not (ws / COPY).exists()
