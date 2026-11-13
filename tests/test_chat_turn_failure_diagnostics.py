"""A failed chat turn leaves a content-free diagnostic line."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import sidecar
from olga_companion.agent import chat, history, session_token
from olga_companion.runtime_logging import LOGGER_NAME


def _failing_builder(_provider: str, _model: str, _variant: str):
    # Provider errors inside generation are handled by the runtime; this fails
    # earlier, while the client is built, which only the route boundary sees.
    raise LookupError("secret-detail-Bearer-abc")


def test_failed_turn_logs_error_kind_without_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("OLGA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    session_id = history.new_session("diagnostics")
    chat.set_client_builder(_failing_builder)
    logger = logging.getLogger(LOGGER_NAME)
    monkeypatch.setattr(logger, "propagate", True)
    try:
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            response = TestClient(sidecar.app).post(
                "/api/chat",
                json={"session_id": session_id, "message": "hello"},
                headers={"X-Session-Token": session_token.boot_token()},
            )
    finally:
        chat.set_client_builder(None)

    assert response.status_code == 200
    assert "event: error" in response.text
    lines = [record.getMessage() for record in caplog.records]
    assert any("chat_turn_failed" in line and "LookupError" in line for line in lines)
    assert all("secret-detail" not in line for line in lines)
