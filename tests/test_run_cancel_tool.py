"""Model cancellation is gated; the direct-human Run control stays immediate."""
import pytest

from olga_companion import workspace
from olga_companion import runner
from olga_companion.agent import approvals, tools


def test_run_cancel_tool_invokes_cancel_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(runner, "cancel_run", lambda run_id: (seen.__setitem__("id", run_id), {"run_id": run_id, "cancelled": True})[1])
    args = {"run_id": "abc123def456"}
    token = approvals.mint(
        "run_cancel",
        tools.approval_payload("run_cancel", args),
        context_generation=workspace.context_generation(),
    )["token"]
    out = tools.dispatch(
        "run_cancel",
        {**args, "approval_token": token, "idempotency_key": "pending-action"},
    )
    assert seen["id"] == "abc123def456"
    assert out["cancelled"] is True


def test_run_cancel_is_registered_and_needs_run_id():
    assert "run_cancel" in tools.TOOLS
    assert "run_id" in tools.TOOLS["run_cancel"].parameters["required"]
    assert tools.TOOLS["run_cancel"].side_effect is True
    with pytest.raises(tools.ToolError, match="approval capability"):
        tools.dispatch("run_cancel", {"run_id": "abc123def456"})
