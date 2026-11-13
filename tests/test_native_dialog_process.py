from __future__ import annotations

import errno
import subprocess
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialogs_test_support import _CompletedProcess

pytest_plugins = ("native_dialogs_test_fixtures",)


def test_atomic_replace_timeout_terminates_and_reaps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    instances = []

    class Hung:
        returncode = None

        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.terminated = False
            self.waited = False
            instances.append(self)

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(self.argv, timeout)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            self.waited = True
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(
        native_dialogs, "_resolve_powershell", lambda: (Path("powershell.exe"), "")
    )
    monkeypatch.setattr(
        native_dialogs, "local_to_windows", lambda path: rf"C:\QA\{Path(path).name}"
    )
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", Hung)

    with pytest.raises(OSError) as raised:
        native_dialogs.replace_file_with_backup(
            tmp_path / "new.pdf",
            tmp_path / "existing.pdf",
            tmp_path / "backup.pdf",
            timeout_s=0.01,
        )

    assert raised.value.errno == errno.ETIMEDOUT
    assert instances[0].terminated is True
    assert instances[0].waited is True


@pytest.mark.parametrize(
    ("payload", "returncode", "reason"),
    [
        (b"not-json", 0, "malformed"),
        (b'{"status":"selected","path":"C:\\\\x"} trailing', 0, "malformed"),
        (b'{"status":"cancelled"}', 7, "failed"),
        (b"x" * (native_dialogs.MAX_OUTPUT_BYTES + 1), 0, "large"),
    ],
)
def test_malformed_oversized_or_nonzero_output_never_selects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
    returncode: int,
    reason: str,
) -> None:
    exe = tmp_path / "powershell.exe"
    exe.write_text("stub")
    exe.chmod(0o755)

    class Process(_CompletedProcess):
        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.returncode = returncode
            kwargs["stdout"].write(payload)

    monkeypatch.setenv("OLGA_POWERSHELL_PATH", str(exe))
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", Process)

    result = native_dialogs.show_dialog("folder", f"bad-{reason}")

    assert result["status"] == "unavailable"
    assert reason.lower() in result["reason"].lower()
    assert native_dialogs.active_request_ids() == []


def test_timeout_kills_reaps_and_unregisters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "powershell.exe"
    exe.write_text("stub")
    exe.chmod(0o755)
    instances = []

    class Hung(_CompletedProcess):
        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.waited = False
            instances.append(self)

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(self.argv, timeout)

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            if self.terminated:
                self.returncode = -15
                return self.returncode
            raise subprocess.TimeoutExpired(self.argv, timeout)

        def kill(self):
            self.killed = True
            self.returncode = -9

    monkeypatch.setenv("OLGA_POWERSHELL_PATH", str(exe))
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", Hung)

    result = native_dialogs.show_dialog("folder", "hung-one", timeout_s=0.01)

    assert result == {"status": "unavailable", "reason": "timeout"}
    assert instances[0].terminated and instances[0].waited
    assert native_dialogs.active_request_ids() == []
