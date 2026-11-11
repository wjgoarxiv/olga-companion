import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    directory = tempfile.TemporaryDirectory(prefix="olga-pytest-")
    environment = pytest.MonkeyPatch()
    config.add_cleanup(directory.cleanup)
    config.add_cleanup(environment.undo)
    environment.setenv("OLGA_APP_DATA_DIR", directory.name)
    environment.setenv("OLGA_APPROVAL_JOURNAL_DIR", str(Path(directory.name) / "approvals"))


@pytest.fixture(autouse=True)
def _isolate_active_case(tmp_path, monkeypatch):
    """No test should touch the real `var/workspace-active.json`. Case tools now set
    the active case on touch (tools._set_active_case), so any test that dispatches a
    case tool would otherwise pollute the developer's live active case. Redirect the
    active-state file to a per-test temp; tests that need their own path (test_workspace,
    test_tools_active) re-patch it in their own fixtures, which wins."""
    from olga_companion import (
        config,
        genkey_static,
        native_dialogs,
        runner,
        sidecar_save_as_retention,
        workspace,
    )
    from olga_companion.agent import approvals, history

    monkeypatch.setattr(
        workspace, "_active_state_path", lambda: tmp_path / "test-active.json"
    )
    monkeypatch.setattr(
        workspace, "_context_state_path", lambda: tmp_path / "test-context.json"
    )
    monkeypatch.setattr(
        config,
        "_workspace_override_path",
        lambda: tmp_path / "test-workspace-root.json",
    )
    monkeypatch.setattr(
        config,
        "_workspace_context_path",
        lambda: tmp_path / "test-context-record.json",
        raising=False,
    )
    monkeypatch.setattr(
        config,
        "_workspace_context_marker_path",
        lambda: tmp_path / "test-context-record.initialized",
        raising=False,
    )
    monkeypatch.setattr(config, "_CONTEXT_INITIALIZED_SEEN", False, raising=False)
    sandbox = tmp_path / "sandbox"
    monkeypatch.setattr(config, "sandbox_root", lambda: sandbox)
    monkeypatch.setattr(genkey_static, "sandbox_root", lambda: sandbox)
    monkeypatch.setattr(runner, "sandbox_root", lambda: sandbox)
    private_state = tmp_path / "private-state"
    monkeypatch.setattr(config, "private_state_root", lambda: private_state)
    chat_history = tmp_path / "chat-history"

    def isolated_chat_history_root():
        chat_history.mkdir(exist_ok=True)
        return chat_history

    monkeypatch.setattr(history, "chats_root", isolated_chat_history_root)
    monkeypatch.setattr(
        sidecar_save_as_retention,
        "_STATE_ROOT",
        tmp_path / "save-as-retention-state",
    )
    approvals.revoke_all()
    native_dialogs.cancel_all()
    yield
    approvals.revoke_all()
    native_dialogs.cancel_all()
