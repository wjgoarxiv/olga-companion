"""Finding the user's own Claude Code CLI on Windows PCs other than the developer's."""

from __future__ import annotations

import pytest

from olga_companion.llm import claude_cli_discovery as disc

FULL_HELP = " ".join(disc.REQUIRED_FLAGS)
HOME = "C:\\Users\\홍 길동"
APPDATA = HOME + "\\AppData\\Roaming"


class FakeFs:
    """Fake Windows filesystem plus a runner that answers --version / --help per executable."""

    def __init__(self, files: dict[str, tuple[str, str]] | None = None, extra: set[str] | None = None):
        self.files = {k.lower(): v for k, v in (files or {}).items()}
        self.extra = {k.lower() for k in (extra or set())}
        self.opened: list[str] = []
        self.ran: list[list[str]] = []

    def exists(self, path: str) -> bool:
        self.opened.append(path)
        return path.lower() in self.files or path.lower() in self.extra

    def run(self, argv: list[str], timeout: float) -> tuple[int, bytes]:
        self.ran.append(list(argv))
        exe = next((a for a in argv if a.lower() in self.files), None)
        if exe is None:
            return 1, b""
        version, help_text = self.files[exe.lower()]
        if version == "TIMEOUT":
            raise TimeoutError
        if argv[-1] == "--version":
            return 0, version.encode("utf-8")
        return 0, help_text.encode("utf-8")


def resolve(fs: FakeFs, *, path: str = "", override: str = "", env: dict[str, str] | None = None):
    base = {"USERPROFILE": HOME, "APPDATA": APPDATA, "PATH": path}
    return disc.resolve(env=env or base, windows=True, exists=fs.exists, run=fs.run, override=override, use_cache=False)


def native(home: str = HOME) -> str:
    return home + "\\.local\\bin\\claude.exe"


def test_native_install_wins_over_path_and_handles_korean_spaced_user_name():
    other = "D:\\tools\\claude.exe"
    fs = FakeFs({native(): ("2.1.220 (Claude Code)", FULL_HELP), other: ("2.1.330 (Claude Code)", FULL_HELP)})
    found = resolve(fs, path="D:\\tools")
    assert found.code == "ok"
    assert found.argv == [native()]
    assert found.version == "2.1.220"


def test_path_lookup_skips_empty_and_relative_entries():
    good = "E:\\bin\\claude.exe"
    fs = FakeFs({"bin\\claude.exe": ("2.1.220", FULL_HELP), good: ("2.1.220", FULL_HELP)})
    found = resolve(fs, path=";bin;;E:\\bin")
    assert found.code == "ok" and found.argv == [good]
    assert not any(p.lower().startswith("bin\\") for p in fs.opened)


def test_nothing_installed_is_not_installed():
    found = resolve(FakeFs(), path="C:\\Windows\\System32")
    assert found.code == "not_installed"


def test_saved_override_is_used_first_and_a_missing_one_is_reported():
    custom = "C:\\Temp\\테스트 사용자 name\\claude.exe"
    fs = FakeFs({custom: ("2.1.220", FULL_HELP), native(): ("2.1.220", FULL_HELP)})
    assert resolve(fs, override=custom).argv == [custom]
    assert resolve(FakeFs({native(): ("2.1.220", FULL_HELP)}), override=custom).code == "override_missing"


def test_missing_flags_are_diagnosed_and_old_versions_named():
    fs = FakeFs({native(): ("2.1.300", "--print --output-format")})
    assert resolve(fs).code == "flags_missing"
    fs_old = FakeFs({native(): ("1.0.80", "--print")})
    assert resolve(fs_old).code == "version_too_old"


def test_probe_timeout_is_its_own_code():
    assert resolve(FakeFs({native(): ("TIMEOUT", "")})).code == "probe_timeout"


def test_npm_shim_prefers_bundled_native_exe_beside_it():
    shim = APPDATA + "\\npm\\claude.cmd"
    bundled = APPDATA + "\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"
    fs = FakeFs({bundled: ("2.1.220", FULL_HELP)}, extra={shim})
    found = resolve(fs)
    assert found.code == "ok" and found.argv == [bundled]


def test_npm_shim_falls_back_to_cmd_only_for_a_safe_path():
    shim = APPDATA + "\\npm\\claude.cmd"
    fs = FakeFs({shim: ("2.1.220", FULL_HELP)})
    found = resolve(fs)
    assert found.code == "ok"
    assert found.argv[:4] == ["cmd.exe", "/d", "/s", "/c"] and found.argv[-1] == shim
    unsafe = "C:\\Users\\a&b\\AppData\\Roaming"
    bad = FakeFs({unsafe + "\\npm\\claude.cmd": ("2.1.220", FULL_HELP)})
    env = {"USERPROFILE": "C:\\Users\\a&b", "APPDATA": unsafe, "PATH": ""}
    assert resolve(bad, env=env).code == "cmd_shim_unsafe"


def test_shim_arguments_are_checked_against_the_cmd_allowlist():
    assert disc.cmd_safe_args(["-p", "--tools", "", "--model", "sonnet"]) is True
    for bad in ("a&b", "x|y", "%PATH%", "!x!", 'q"', "a^b", "<in", ">out"):
        assert disc.cmd_safe_args(["--model", bad]) is False


def test_override_validation_refuses_other_executables(tmp_path):
    other = tmp_path / "notepad.exe"
    other.write_bytes(b"")
    with pytest.raises(disc.ClaudeCliOverrideError):
        disc.validate_override(str(other))
    with pytest.raises(disc.ClaudeCliOverrideError):
        disc.validate_override("relative\\claude.exe")
    good = tmp_path / "claude.exe"
    good.write_bytes(b"")
    assert disc.validate_override(str(good)) == str(good.resolve())


def test_discovery_never_touches_claude_credential_folders():
    fs = FakeFs({native(): ("2.1.220", FULL_HELP)})
    resolve(fs, path="C:\\a;C:\\b")
    assert not any("\\.claude\\" in p.lower() or p.lower().endswith("\\.claude") for p in fs.opened)


def test_version_output_in_the_oem_code_page_still_parses():
    assert disc.parse_version("2.1.220 (Claude Code)".encode("cp949")) == "2.1.220"
    assert disc.parse_version(b"\xa1\xa4 garbage") == ""


def test_non_windows_uses_plain_claude_on_path():
    fs = FakeFs({"/usr/local/bin/claude": ("2.1.330", FULL_HELP)})
    found = disc.resolve(env={"HOME": "/home/u", "PATH": "/usr/local/bin"}, windows=False, exists=fs.exists,
                         run=fs.run, override="", use_cache=False)
    assert found.code == "ok" and found.argv == ["/usr/local/bin/claude"]


def test_a_cmd_shim_in_a_path_with_spaces_is_quoted_the_same_for_the_probe_and_the_launch(monkeypatch):
    shim = r"C:\Users\Jane Doe\AppData\Roaming\npm\claude.cmd"
    argv = ["cmd.exe", "/d", "/s", "/c", shim, "--version"]
    line = disc.windows_command(argv)
    assert line == 'cmd.exe /d /s /c ""C:\\Users\\Jane Doe\\AppData\\Roaming\\npm\\claude.cmd" --version"'
    assert disc.windows_command(["C:\\x\\claude.exe", "-p"]) == ["C:\\x\\claude.exe", "-p"]
    seen = []

    class Done:
        returncode, stdout, stderr = 0, b"2.1.330 (Claude Code)", b""

    monkeypatch.setattr(disc.sys, "platform", "win32")
    monkeypatch.setattr(disc.subprocess, "run", lambda command, **_kw: seen.append(command) or Done())
    disc._default_run(argv, 5)
    assert seen == [line]
