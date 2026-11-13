from __future__ import annotations

import base64
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialogs_test_support import _CompletedProcess

pytest_plugins = ("native_dialogs_test_fixtures",)


def test_dialog_is_honestly_unavailable_without_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLGA_POWERSHELL_PATH", raising=False)
    monkeypatch.setattr(native_dialogs, "_powershell_candidates", lambda: [])

    result = native_dialogs.show_dialog("folder", "missing-exe")

    assert result["status"] == "unavailable"
    assert "PowerShell" in result["reason"]
    assert native_dialogs.active_request_ids() == []


def test_missing_wslinterop_launches_powershell_through_wsl_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "powershell.exe"
    exe.write_text("stub")
    exe.chmod(0o755)
    monkeypatch.setenv("OLGA_POWERSHELL_PATH", str(exe))
    monkeypatch.setattr(native_dialogs, "WSL_INTEROP_PATH", tmp_path / "missing")
    captured = []

    def popen(argv, **kwargs):
        process = _CompletedProcess(argv, **kwargs)
        captured.append(process)
        return process

    monkeypatch.setattr(native_dialogs.subprocess, "Popen", popen)

    result = native_dialogs.show_dialog("folder", "no-wslinterop")

    assert result == {"status": "cancelled"}
    assert captured[0].argv[:2] == ["/init", str(exe)]
    assert "OLGA_DIALOG_KIND/w" in captured[0].kwargs["env"]["WSLENV"]
    assert native_dialogs.active_request_ids() == []


def test_dialog_uses_fixed_encoded_argv_and_bounded_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "powershell.exe"
    exe.write_text("stub")
    exe.chmod(0o755)
    captured: list[_CompletedProcess] = []

    def popen(argv, **kwargs):
        proc = _CompletedProcess(argv, **kwargs)
        captured.append(proc)
        return proc

    monkeypatch.setenv("OLGA_POWERSHELL_PATH", str(exe))
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", popen)
    untrusted = "name'; Write-Output PWNED; '"

    result = native_dialogs.show_dialog("save-as", "safe-id", suggested_name=untrusted)

    assert result == {"status": "cancelled"}
    proc = captured[0]
    assert proc.kwargs.get("shell", False) is False
    assert proc.argv[:5] == [
        str(exe),
        "-NoProfile",
        "-NonInteractive",
        "-STA",
        "-EncodedCommand",
    ]
    assert len(proc.argv) == 6
    assert untrusted not in " ".join(proc.argv)
    assert proc.kwargs["env"]["OLGA_DIALOG_SUGGESTED"] == untrusted
    decoded = base64.b64decode(proc.argv[-1]).decode("utf-16le")
    assert decoded == native_dialogs.POWERSHELL_DIALOG_SCRIPT
    assert native_dialogs.active_request_ids() == []


def test_atomic_replace_uses_fixed_encoded_argv_and_environment_only_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    captured: list[_CompletedProcess] = []

    class ReplaceProcess(_CompletedProcess):
        def __init__(self, argv, **kwargs):
            super().__init__(argv, **kwargs)
            kwargs["stdout"].seek(0)
            kwargs["stdout"].truncate()
            kwargs["stdout"].write(b"ok")

    def popen(argv, **kwargs):
        process = ReplaceProcess(argv, **kwargs)
        captured.append(process)
        return process

    monkeypatch.setattr(native_dialogs, "_resolve_powershell", lambda: (executable, ""))
    monkeypatch.setattr(
        native_dialogs,
        "local_to_windows",
        lambda path: rf"C:\QA\{Path(path).name}",
    )
    monkeypatch.setattr(native_dialogs.subprocess, "Popen", popen)
    replacement = tmp_path / "new'; Write-Output PWNED; '.pdf"
    destination = tmp_path / "existing.pdf"
    backup = tmp_path / "backup.pdf"

    native_dialogs.replace_file_with_backup(replacement, destination, backup)

    process = captured[0]
    assert process.argv == [
        str(executable),
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        native_dialogs._ENCODED_REPLACE_SCRIPT,
    ]
    assert str(replacement) not in " ".join(process.argv)
    assert process.kwargs["env"]["OLGA_REPLACE_SOURCE"] == rf"C:\QA\{replacement.name}"
    assert process.kwargs["env"]["OLGA_REPLACE_DESTINATION"] == r"C:\QA\existing.pdf"
    assert process.kwargs["env"]["OLGA_REPLACE_BACKUP"] == r"C:\QA\backup.pdf"
    decoded = base64.b64decode(process.argv[-1]).decode("utf-16le")
    assert decoded == native_dialogs.POWERSHELL_REPLACE_SCRIPT
    assert process.kwargs.get("shell", False) is False
    assert process.kwargs["close_fds"] is True
