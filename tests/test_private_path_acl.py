from __future__ import annotations

import errno
import os
import stat
import subprocess
from pathlib import Path

import pytest

from olga_companion import private_path_acl


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX mode contract; Windows cannot honour chmod 0o700/0o600",
)
def test_posix_private_paths_require_exact_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o755)
    file_path = directory / "record.json"
    file_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(private_path_acl, "_windows_path", lambda _path: None)

    private_path_acl.harden_private_path(directory, directory=True)
    private_path_acl.harden_private_path(file_path, directory=False)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(file_path.stat().st_mode) == 0o600


def test_private_path_hardening_fails_closed_when_acl_cannot_be_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "private"
    path.mkdir()
    monkeypatch.setattr(
        private_path_acl,
        "_windows_path",
        lambda _path: r"C:\private",
    )
    monkeypatch.setattr(
        private_path_acl,
        "_apply_windows_acl",
        lambda _path, *, directory: (_ for _ in ()).throw(
            OSError(errno.EACCES, "ACL verification failed")
        ),
    )

    with pytest.raises(OSError, match="ACL verification failed"):
        private_path_acl.harden_private_path(path, directory=True)


@pytest.mark.skipif(
    os.name == "nt",
    reason="WSL /mnt/<drive> translation contract; POSIX path semantics only",
)
def test_wsl_drive_paths_translate_without_shell_interpolation() -> None:
    translated = private_path_acl._windows_path(
        Path("/mnt/c/Users/Woojin/shared folder/result.csv")
    )

    assert translated == r"C:\Users\Woojin\shared folder\result.csv"
    assert private_path_acl._windows_path(Path("/tmp/result.csv")) is None


def test_acl_program_protects_and_verifies_exact_allow_identities() -> None:
    program = private_path_acl._WINDOWS_ACL_SCRIPT

    assert "SetAccessRuleProtection($true, $false)" in program
    assert "S-1-5-18" in program
    assert "S-1-5-32-544" in program
    assert "AreAccessRulesProtected" in program
    assert "AccessControlType]::Allow" in program
    assert "exit 23" in program


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "POSIX/WSL export contract; patching os.name to 'posix' on native "
        "Windows makes a failure surface as a pytest INTERNALERROR "
        "(PosixPath cannot be instantiated) that aborts the whole session"
    ),
)
def test_wsl_acl_call_exports_private_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    def fake_run(*_args, **kwargs) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        observed.update(environment)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(private_path_acl.os, "name", "posix")
    monkeypatch.setattr(
        private_path_acl, "_powershell_executable", lambda: Path("powershell.exe")
    )
    monkeypatch.setattr(private_path_acl.subprocess, "run", fake_run)
    monkeypatch.setenv("WSLENV", "EXISTING/u:OLGA_PRIVATE_KIND")

    private_path_acl._apply_windows_acl(r"C:\private path", directory=True)

    assert observed["OLGA_PRIVATE_PATH"] == r"C:\private path"
    assert observed["OLGA_PRIVATE_KIND"] == "directory"
    assert observed["WSLENV"] == "EXISTING/u:OLGA_PRIVATE_KIND:OLGA_PRIVATE_PATH"


def test_posix_hardening_error_is_not_suppressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "private"
    path.mkdir()
    monkeypatch.setattr(private_path_acl, "_windows_path", lambda _path: None)
    monkeypatch.setattr(
        os,
        "chmod",
        lambda _path, _mode: (_ for _ in ()).throw(
            OSError(errno.EPERM, "mode hardening failed")
        ),
    )

    with pytest.raises(OSError, match="mode hardening failed"):
        private_path_acl.harden_private_path(path, directory=True)
