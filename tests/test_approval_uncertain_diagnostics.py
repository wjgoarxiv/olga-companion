"""An approval that ends uncertain or failed leaves its cause in sidecar.log.

The diagnostics bundle only carries the runtime-diagnostics logger. Before this,
a dispatch that raised was sealed as 409 approval_dispatch_uncertain with no line
saying which action failed or why, so a bug report could not be diagnosed.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import workspace
from olga_companion.agent import pending_approvals, session_token, tools
from olga_companion.runtime_logging import LOGGER_NAME
import olga_companion.sidecar as sidecar


class DispatchProbeError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _clear_pending_approvals():
    pending_approvals.revoke_all()
    yield
    pending_approvals.revoke_all()


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> tuple[TestClient, dict]:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n", encoding="utf-8")
    api = TestClient(sidecar.app, raise_server_exceptions=False)
    created = api.post("/api/chat/session", json={"title": ""}, headers=_headers())
    session_id = str(created.json()["session_id"])
    generation = workspace.context_generation()
    pending_id = pending_approvals.register(
        action_kind="run_execute",
        args={"source": str(case), "timeout_s": 3600, "selection_id": "selection-1"},
        call_id="call-1",
        context_generation=generation,
        session_id=session_id,
    )
    monkeypatch.setattr(logging.getLogger(LOGGER_NAME), "propagate", True)
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    payload = {
        "pending_id": pending_id,
        "session_id": session_id,
        "call_id": "call-1",
        "context_generation": generation,
    }
    return api, payload


def _diag_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]


def test_dispatch_exception_logs_action_kind_and_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    api, payload = _setup(tmp_path, monkeypatch, caplog)

    def broken_dispatch(_name: str, _args: dict) -> dict:
        raise DispatchProbeError("opi refused Bearer sk-secret123456789 at step 2")

    monkeypatch.setattr(sidecar.tools, "dispatch", broken_dispatch)

    response = api.post("/api/approvals/execute", json=payload, headers=_headers())

    assert response.status_code == 409
    assert response.json()["code"] == "approval_dispatch_uncertain"
    lines = [line for line in _diag_lines(caplog) if line.startswith("approval_uncertain")]
    assert len(lines) == 1, _diag_lines(caplog)
    line = lines[0]
    assert "action=run_execute" in line
    assert "kind=DispatchProbeError" in line
    assert "at=test_approval_uncertain_diagnostics.py:" in line
    assert "opi refused" in line
    assert "sk-secret123456789" not in line


def test_tool_error_after_dispatch_logs_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    api, payload = _setup(tmp_path, monkeypatch, caplog)

    def tool_error_dispatch(_name: str, _args: dict) -> dict:
        raise tools.ToolError("run handler lost the OLGA process")

    monkeypatch.setattr(sidecar.tools, "dispatch", tool_error_dispatch)

    response = api.post("/api/approvals/execute", json=payload, headers=_headers())

    assert response.status_code == 409
    lines = [line for line in _diag_lines(caplog) if line.startswith("approval_uncertain")]
    assert len(lines) == 1, _diag_lines(caplog)
    assert "action=run_execute" in lines[0]
    assert "kind=ToolError" in lines[0]
    assert "lost the OLGA process" in lines[0]


def test_known_failure_logs_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    api, payload = _setup(tmp_path, monkeypatch, caplog)

    def failed_dispatch(_name: str, _args: dict) -> dict:
        raise tools.ToolFailedError("OLGA license server did not answer")

    monkeypatch.setattr(sidecar.tools, "dispatch", failed_dispatch)

    response = api.post("/api/approvals/execute", json=payload, headers=_headers())

    assert response.status_code == 200
    assert response.json()["state"] == "failed"
    lines = [line for line in _diag_lines(caplog) if line.startswith("approval_failed")]
    assert len(lines) == 1, _diag_lines(caplog)
    assert "action=run_execute" in lines[0]
    assert "kind=ToolFailedError" in lines[0]
    assert "license server did not answer" in lines[0]


def test_replayed_uncertain_click_logs_the_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    api, payload = _setup(tmp_path, monkeypatch, caplog)

    def broken_dispatch(_name: str, _args: dict) -> dict:
        raise DispatchProbeError("boom")

    monkeypatch.setattr(sidecar.tools, "dispatch", broken_dispatch)
    api.post("/api/approvals/execute", json=payload, headers=_headers())
    caplog.clear()

    replay = api.post("/api/approvals/execute", json=payload, headers=_headers())

    assert replay.status_code == 409
    lines = [line for line in _diag_lines(caplog) if line.startswith("approval_uncertain")]
    assert len(lines) == 1, _diag_lines(caplog)
    assert "action=run_execute" in lines[0]
    assert "stage=replay" in lines[0]
