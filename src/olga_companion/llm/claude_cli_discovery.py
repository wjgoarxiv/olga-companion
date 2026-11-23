"""Find the user's own installed Claude Code CLI and check that it can run as a chat backend.

Only executables are looked up and asked for ``--version`` / ``--help``. Nothing under the
user's Claude configuration or credential folders is ever opened: sign-in stays inside the
CLI, which the user runs and signs in to themselves.
"""

from __future__ import annotations

import json
import ntpath
import os
import posixpath
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .. import config

REQUIRED_FLAGS = (
    "--print",
    "--tools",
    "--mcp-config",
    "--strict-mcp-config",
    "--setting-sources",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--output-format",
    "--verbose",
    "--allowedTools",
    "--model",
)
# Below this, a CLI missing flags is called out as too old rather than as "missing flags".
OLD_VERSION = (2, 1, 0)
PROBE_TIMEOUT_S = 10.0
CACHE_TTL_S = 30.0
OVERRIDE_NAMES = frozenset({"claude", "claude.exe", "claude.cmd"})
# cmd.exe re-parses a .cmd shim's command line, so these characters would change its meaning.
_CMD_UNSAFE = re.compile(r'[&|<>^%!"\r\n]')
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_NO_WINDOW = 0x08000000

Runner = Callable[[list[str], float], tuple[int, bytes]]


class ClaudeCliOverrideError(ValueError):
    """The saved manual CLI path is missing or not a Claude Code executable."""


@dataclass(frozen=True)
class CliResolution:
    """``code`` is ``ok`` or a diagnosis; ``argv`` is the launch prefix when ``ok``."""

    code: str
    argv: list[str] = field(default_factory=list)
    path: str = ""
    version: str = ""


def parse_version(output: bytes) -> str:
    match = _VERSION.search(output.decode("utf-8", errors="replace"))
    return ".".join(match.groups()) if match else ""


def cmd_safe_args(args: list[str]) -> bool:
    return not any(_CMD_UNSAFE.search(arg) for arg in args)


def windows_command(argv: list[str]) -> list[str] | str:
    """The command line for a guarded ``cmd.exe /d /s /c`` shim: /s strips one outer pair of quotes."""
    if argv[:4] == ["cmd.exe", "/d", "/s", "/c"]:
        return 'cmd.exe /d /s /c "' + subprocess.list2cmdline(argv[4:]) + '"'
    return argv


def _default_run(argv: list[str], timeout: float) -> tuple[int, bytes]:
    windows = sys.platform == "win32"
    try:
        done = subprocess.run(windows_command(argv) if windows else argv, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout, creationflags=_NO_WINDOW if windows else 0)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError from exc
    return done.returncode, done.stdout + done.stderr


def _path_mod(windows: bool):
    return ntpath if windows else posixpath


def _absolute(path: str, windows: bool) -> bool:
    if windows:
        drive, rest = ntpath.splitdrive(path)
        return bool(drive) and rest.startswith(("\\", "/"))
    return path.startswith("/")


def _shim_launch(shim: str, exists: Callable[[str], bool]) -> list[str] | None:
    """An npm ``claude.cmd``: prefer the native exe the package ships, else a guarded cmd.exe."""
    bundled = ntpath.join(ntpath.dirname(shim), "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
    if exists(bundled):
        return [bundled]
    if _CMD_UNSAFE.search(shim):
        return None
    return ["cmd.exe", "/d", "/s", "/c", shim]


def _candidates(env: Mapping[str, str], windows: bool, override: str) -> list[tuple[str, str]]:
    """(kind, path) in search order: override, native install, npm shim, PATH entries."""
    out: list[tuple[str, str]] = []
    if override:
        out.append(("override", override))
    mod = _path_mod(windows)
    if windows:
        home = env.get("USERPROFILE", "")
        if home and _absolute(home, True):
            out.append(("exe", ntpath.join(home, ".local", "bin", "claude.exe")))
        appdata = env.get("APPDATA", "")
        if appdata and _absolute(appdata, True):
            out.append(("cmd", ntpath.join(appdata, "npm", "claude.cmd")))
    else:
        home = env.get("HOME", "")
        if home and _absolute(home, False):
            out.append(("exe", posixpath.join(home, ".local", "bin", "claude")))
    for entry in env.get("PATH", "").split(";" if windows else ":"):
        entry = entry.strip().strip('"')
        if not entry or not _absolute(entry, windows):
            continue
        if windows:
            out.append(("exe", ntpath.join(entry, "claude.exe")))
            out.append(("cmd", ntpath.join(entry, "claude.cmd")))
        else:
            out.append(("exe", mod.join(entry, "claude")))
    return out


def _probe(argv: list[str], path: str, run: Runner) -> CliResolution:
    try:
        code, out = run([*argv, "--version"], PROBE_TIMEOUT_S)
        if code != 0:
            return CliResolution("not_executable", path=path)
        version = parse_version(out)
        code, help_out = run([*argv, "--help"], PROBE_TIMEOUT_S)
    except TimeoutError:
        return CliResolution("probe_timeout", path=path)
    except OSError:
        return CliResolution("not_executable", path=path)
    help_text = help_out.decode("utf-8", errors="replace")
    if code != 0 or any(flag not in help_text for flag in REQUIRED_FLAGS):
        parts = tuple(int(p) for p in version.split(".")) if version else (0, 0, 0)
        return CliResolution("version_too_old" if parts < OLD_VERSION else "flags_missing", path=path, version=version)
    return CliResolution("ok", argv=list(argv), path=path, version=version)


_cache: dict[str, tuple[float, CliResolution]] = {}


def invalidate() -> None:
    _cache.clear()


_refreshing = threading.Event()


def peek_now() -> CliResolution | None:
    """The last resolution, at once; a stale or missing one is refreshed in the background.

    Status polls use this so they never wait on ``claude --version``/``--help``.
    """
    override = load_override()
    cached = _cache.get(override)
    if (cached is None or time.monotonic() - cached[0] >= CACHE_TTL_S) and not _refreshing.is_set():
        _refreshing.set()

        def work() -> None:
            try:
                resolve()
            finally:
                _refreshing.clear()

        threading.Thread(target=work, daemon=True).start()
    return cached[1] if cached is not None else None


peek = peek_now


def resolve(
    *,
    env: Mapping[str, str] | None = None,
    windows: bool | None = None,
    exists: Callable[[str], bool] | None = None,
    run: Runner | None = None,
    override: str | None = None,
    use_cache: bool = True,
) -> CliResolution:
    """Return the first usable CLI in search order, or the most specific diagnosis."""
    env = os.environ if env is None else env
    windows = sys.platform == "win32" if windows is None else windows
    exists = os.path.isfile if exists is None else exists
    run = _default_run if run is None else run
    override = load_override() if override is None else override
    key = override
    if use_cache and key in _cache and time.monotonic() - _cache[key][0] < CACHE_TTL_S:
        return _cache[key][1]
    result = _resolve(env, windows, exists, run, override)
    if use_cache:
        _cache[key] = (time.monotonic(), result)
    return result


def _resolve(env, windows, exists, run, override) -> CliResolution:
    first_problem: CliResolution | None = None
    for kind, path in _candidates(env, windows, override):
        if not exists(path):
            if kind == "override":
                return CliResolution("override_missing", path=path)
            continue
        if kind == "cmd" or (kind == "override" and path.lower().endswith(".cmd")):
            argv = _shim_launch(path, exists)
            if argv is None:
                first_problem = first_problem or CliResolution("cmd_shim_unsafe", path=path)
                continue
        else:
            argv = [path]
        found = _probe(argv, path, run)
        if found.code == "ok" or kind == "override":
            return found
        first_problem = first_problem or found
    return first_problem or CliResolution("not_installed")


def override_path() -> Path:
    """Non-secret operator choice: the Settings-picked Claude Code executable."""
    return config.project_root() / "var" / "claude-cli-override.json"


def load_override() -> str:
    path = override_path()
    if not path.is_file():
        return ""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = record.get("exe") if isinstance(record, dict) else None
    return value if isinstance(value, str) else ""


def validate_override(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(ch) < 32 for ch in value):
        raise ClaudeCliOverrideError("The Claude Code path is invalid.")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ClaudeCliOverrideError("The Claude Code path must be absolute.")
    if not candidate.is_file():
        raise ClaudeCliOverrideError("The Claude Code path must be an existing file.")
    if candidate.name.lower() not in OVERRIDE_NAMES:
        raise ClaudeCliOverrideError("Pick claude.exe or claude.cmd.")
    return str(candidate.resolve())


def save_override(value: str) -> str:
    resolved = validate_override(value)
    config._atomic_write(override_path(), {"exe": resolved})
    invalidate()
    return resolved


def clear_override() -> bool:
    invalidate()
    try:
        override_path().unlink()
    except FileNotFoundError:
        return False
    return True
