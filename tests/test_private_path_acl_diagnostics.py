"""Frozen-sidecar ACL failures must leave a redacted, bounded diagnosis."""

from __future__ import annotations

import errno
import logging
import os
import subprocess
from pathlib import Path

import pytest

from olga_companion import private_path_acl
from olga_companion.runtime_logging import LOGGER_NAME


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def captured_log() -> _Capture:
    logger = logging.getLogger(LOGGER_NAME)
    handler = _Capture()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(previous_level)


@pytest.fixture
def fake_powershell(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace the PowerShell child with a recorder whose result is settable."""
    state: dict[str, object] = {
        "returncode": 0,
        "stderr": b"",
        "calls": [],
    }

    def fake_run(args, **kwargs):
        state["calls"].append((list(args), kwargs))
        return subprocess.CompletedProcess(
            args, int(state["returncode"]), b"", state["stderr"]
        )

    monkeypatch.setattr(
        private_path_acl, "_powershell_executable", lambda: Path("powershell.exe")
    )
    monkeypatch.setattr(private_path_acl.subprocess, "run", fake_run)
    return state


def test_exit_zero_passes_without_a_log_line(
    fake_powershell: dict[str, object], captured_log: _Capture
) -> None:
    private_path_acl._apply_windows_acl(r"C:\private", directory=True)

    assert len(fake_powershell["calls"]) == 1
    assert captured_log.lines == []


def test_non_zero_exit_reports_only_the_code_and_stays_fail_closed(
    fake_powershell: dict[str, object], captured_log: _Capture
) -> None:
    fake_powershell["returncode"] = 23

    with pytest.raises(OSError) as raised:
        private_path_acl._apply_windows_acl(r"C:\private", directory=False)

    assert raised.value.errno == errno.EACCES
    assert raised.value.strerror == "Windows ACL verification failed (code 23)."
    assert len(captured_log.lines) == 1
    line = captured_log.lines[0]
    assert line.startswith("private_acl_failed kind=file code=23 detail=")


def test_the_log_detail_is_a_redacted_bounded_tail(
    fake_powershell: dict[str, object],
    captured_log: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("USER", raising=False)
    sid = "S-1-5-21-1111111111-2222222222-3333333333-1001"
    stderr = (
        "A" * 900
        + " Set-Acl : Attempted to perform an unauthorized operation on "
        + "C:\\Users\\Jordan Example\\.olga_copilot\\case-transactions\\.transaction-x "
        + f"for Jordan Example ({sid}) \\\\server\\share\\x "
        + "D:\\Program Files\\OLGA\\sample.tab"
    ).encode("utf-8")
    fake_powershell["returncode"] = 1
    fake_powershell["stderr"] = stderr
    target = r"C:\private\other-file"

    with pytest.raises(OSError) as raised:
        private_path_acl._apply_windows_acl(target, directory=True)

    assert raised.value.strerror == "Windows ACL verification failed (code 1)."
    detail = captured_log.lines[0].partition("detail=")[2]
    assert "kind=directory code=1" in captured_log.lines[0]
    assert 0 < len(detail) <= 300
    for secret in (
        "Jordan",
        "Example",
        "Users",
        "olga_copilot",
        "case-transactions",
        sid,
        "S-1-5-21",
        "server",
        "other",
        "C:\\",
        "D:\\",
        "Program",
        "Files",
    ):
        assert secret not in captured_log.lines[0], secret
    assert "Set-Acl" in detail  # the useful part of the message survives
    assert "<path>" in detail or "<user>" in detail
    assert "<sid>" in detail
    assert "\n" not in captured_log.lines[0]


def test_home_directory_never_reaches_the_log(
    fake_powershell: dict[str, object],
    captured_log: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = str(Path.home())
    fake_powershell["returncode"] = 20
    fake_powershell["stderr"] = f"cannot read {home} now".encode()

    with pytest.raises(OSError):
        private_path_acl._apply_windows_acl(r"C:\private", directory=True)

    assert home not in captured_log.lines[0]


def test_timeout_and_launch_failures_are_logged_and_stay_fail_closed(
    captured_log: _Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        private_path_acl, "_powershell_executable", lambda: Path("powershell.exe")
    )

    def timed_out(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 15)

    monkeypatch.setattr(private_path_acl.subprocess, "run", timed_out)
    with pytest.raises(OSError) as raised:
        private_path_acl._apply_windows_acl(r"C:\private", directory=True)
    assert raised.value.errno == errno.EACCES
    assert "private_acl_failed kind=directory code=timeout" in captured_log.lines[0]

    def refused(args, **kwargs):
        raise PermissionError(errno.EACCES, r"denied C:\Users\Someone\x")

    monkeypatch.setattr(private_path_acl.subprocess, "run", refused)
    with pytest.raises(OSError) as raised:
        private_path_acl._apply_windows_acl(r"C:\private", directory=False)
    assert raised.value.errno == errno.EACCES
    assert "private_acl_failed kind=file code=oserror" in captured_log.lines[1]
    assert "Someone" not in captured_log.lines[1]


def test_powershell_call_keeps_its_shape_and_captures_stderr_for_the_log(
    fake_powershell: dict[str, object],
) -> None:
    private_path_acl._apply_windows_acl(r"C:\private", directory=True)

    args, kwargs = fake_powershell["calls"][0]
    assert args[-2] == "-Command"
    assert args[-1] == private_path_acl._WINDOWS_ACL_SCRIPT
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["timeout"] == 15
    assert kwargs["check"] is False


def test_allowed_sids_are_unique_when_the_user_is_system() -> None:
    """A SYSTEM process is already S-1-5-18, so the allow-list must not count it twice."""
    program = private_path_acl._WINDOWS_ACL_SCRIPT
    assert ".Contains(" in program or "Select-Object -Unique" in program


def test_acl_program_writes_with_set_access_control_not_set_acl() -> None:
    program = private_path_acl._WINDOWS_ACL_SCRIPT

    assert "Set-Acl" not in program
    assert ".SetAccessControl($security)" in program
    # Verification is unchanged and still follows the write.
    assert program.index(".SetAccessControl($security)") < program.index("Get-Acl")


def _real_acl_scratch_root() -> Path | None:
    """A folder the real PowerShell can address, or None when there is none."""
    probe = Path(__file__).resolve().parents[1] / ".litclaude" / "tmp"
    if os.name == "nt":
        return probe
    if private_path_acl._windows_path(probe) is None:
        return None
    try:
        private_path_acl._powershell_executable()
    except OSError:
        return None
    return probe


@pytest.mark.parametrize("directory", [True, False])
def test_real_powershell_hardens_the_same_path_repeatedly(directory: bool) -> None:
    """Set-Acl lacks SeSecurityPrivilege on a second pass over a protected ACL."""
    import shutil
    import tempfile

    root = _real_acl_scratch_root()
    if root is None:
        pytest.skip("No Windows PowerShell reachable from this interpreter.")
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="acl-repeat-", dir=root))
    try:
        target = scratch / "subject"
        if directory:
            target.mkdir()
        else:
            target.write_bytes(b"{}")
        for _attempt in range(3):
            private_path_acl.harden_private_path(target, directory=directory)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
