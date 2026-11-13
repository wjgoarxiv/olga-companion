from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import native_dialogs
from olga_companion.sidecar import app

from native_dialogs_test_support import _CompletedProcess

pytest_plugins = ("native_dialogs_test_fixtures",)


def test_cancel_race_terminates_exact_process_and_duplicate_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "powershell.exe"
    exe.write_text("stub")
    exe.chmod(0o755)
    started = threading.Event()
    released = threading.Event()
    instances = []

    class Blocking(_CompletedProcess):
        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.returncode = None
            self.terminated = False
            instances.append(self)
            started.set()

        def communicate(self, timeout=None):
            released.wait(2)
            return (None, None)

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            released.set()

        def wait(self, timeout=None):
            released.wait(2)
            return self.returncode

    monkeypatch.setenv("OLGA_POWERSHELL_PATH", str(exe))
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", Blocking)
    result_holder: list[dict] = []
    thread = threading.Thread(
        target=lambda: result_holder.append(
            native_dialogs.show_dialog("folder", "race-id")
        )
    )
    thread.start()
    assert started.wait(1)

    duplicate = native_dialogs.show_dialog("folder", "race-id")
    cancelled = native_dialogs.cancel_dialog("race-id")
    thread.join(2)

    assert (
        duplicate["status"] == "unavailable"
        and "duplicate" in duplicate["reason"].lower()
    )
    assert cancelled == {"status": "cancelled", "request_id": "race-id"}
    assert instances[0].terminated
    assert result_holder[0]["status"] != "selected"
    assert native_dialogs.active_request_ids() == []


@pytest.mark.parametrize("request_id", ["", "../bad", "has space", "a" * 65])
def test_request_ids_are_strict_bounded_tokens(request_id: str) -> None:
    with pytest.raises(native_dialogs.NativeDialogError):
        native_dialogs.show_dialog("folder", request_id)


def test_fastapi_shutdown_terminates_reaps_and_unregisters_active_dialog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "powershell.exe"
    exe.write_text("stub")
    exe.chmod(0o755)
    started = threading.Event()
    released = threading.Event()
    instances = []

    class Blocking(_CompletedProcess):
        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.returncode = None
            self.terminated = False
            self.waited = False
            instances.append(self)
            started.set()

        def communicate(self, timeout=None):
            released.wait(5)
            return (None, None)

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            released.set()

        def wait(self, timeout=None):
            self.waited = True
            released.wait(1)
            return self.returncode

    monkeypatch.setenv("OLGA_POWERSHELL_PATH", str(exe))
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", Blocking)
    thread = threading.Thread(
        target=lambda: native_dialogs.show_dialog("folder", "shutdown-active")
    )

    with TestClient(app):
        thread.start()
        assert started.wait(1)
        assert native_dialogs.active_request_ids() == ["shutdown-active"]

    active_after_shutdown = native_dialogs.active_request_ids()
    terminated_on_shutdown = instances[0].terminated
    waited_on_shutdown = instances[0].waited
    if thread.is_alive():
        native_dialogs.cancel_all()
    thread.join(2)

    assert terminated_on_shutdown
    assert waited_on_shutdown
    assert active_after_shutdown == []
    assert not thread.is_alive()
