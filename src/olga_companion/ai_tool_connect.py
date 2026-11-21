"""Settings "Connect AI tools" (0.1.20 row 15): add or remove only the app's own MCP entry.

Codex (`~/.codex/config.toml`) and Gemini CLI (`~/.gemini/settings.json`) are written by
file, after a backup, and only when the file parses. Claude Code's docs say not to edit
`~/.claude.json`, so it gets the commands to paste instead (owner decision 2026-11-19).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any, Final

from . import bridge_registry
from .mcp_bridge import SECRET_ENV

ENTRY: Final = "olga-companion"
_BEGIN: Final = f"# >>> {ENTRY} (added by OLGA Companion; use Remove in its Settings)"
_END: Final = f"# <<< {ENTRY}"
_BLOCK: Final = re.compile(rf"\n?{re.escape(_BEGIN)}\n.*?{re.escape(_END)}\n?", re.DOTALL)


class ConnectError(ValueError):
    """The tool's config could not be changed safely; nothing was written."""


def _home() -> Path:
    return Path.home()


def bridge_command() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp"]
    return sys.executable, ["-m", "olga_companion.sidecar", "--mcp"]


def _config_path(product: str) -> Path | None:
    if product == "codex":
        codex_home = os.environ.get("CODEX_HOME")
        path = (Path(codex_home) if codex_home else _home() / ".codex") / "config.toml"
    elif product == "gemini":
        path = _home() / ".gemini" / "settings.json"
    else:
        return None
    # A dotfile manager's symlink stays a symlink: change the file it points to.
    return path.resolve() if path.is_symlink() else path


def _write_bytes(path: Path, data: bytes) -> None:
    """Atomic, byte-exact (no newline translation), keeping the file's permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False)
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copymode(path, temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _entry(secret: str) -> dict[str, Any]:
    command, args = bridge_command()
    return {"command": command, "args": args, "env": {SECRET_ENV: secret}}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def _codex_text(original: str, secret: str) -> str:
    try:
        parsed = tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        raise ConnectError("The Codex config file could not be read, so it was left unchanged.") from exc
    base = _BLOCK.sub("", original) if _BEGIN in original else original
    if ENTRY in tomllib.loads(base).get("mcp_servers", {}):
        raise ConnectError(f"The Codex config already has an entry named {ENTRY} that OLGA Companion did not write; remove it first.")
    del parsed
    entry = _entry(secret)
    block = "\n".join(
        [
            _BEGIN,
            f"[mcp_servers.{ENTRY}]",
            f"command = {_toml_string(entry['command'])}",
            "args = [" + ", ".join(_toml_string(arg) for arg in entry["args"]) + "]",
            "",
            f"[mcp_servers.{ENTRY}.env]",
            f"{SECRET_ENV} = {_toml_string(secret)}",
            _END,
            "",
        ]
    )
    separator = "" if not base or base.endswith("\n") else "\n"
    text = base + separator + "\n" + block if base else block
    tomllib.loads(text)  # never write a file the tool could not read back
    return text


def _gemini_text(original: str, secret: str) -> str:
    try:
        data = json.loads(original) if original.strip() else {}
    except ValueError as exc:
        raise ConnectError("The Gemini CLI settings file could not be read, so it was left unchanged.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise ConnectError("The Gemini CLI settings file could not be read, so it was left unchanged.")
    servers = data.setdefault("mcpServers", {})
    existing = servers.get(ENTRY)
    if existing is not None and not (isinstance(existing, dict) and SECRET_ENV in existing.get("env", {})):
        raise ConnectError(f"The Gemini CLI settings already have an entry named {ENTRY} that OLGA Companion did not write; remove it first.")
    servers[ENTRY] = _entry(secret)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _without_entry(product: str, text: str) -> str:
    if product == "codex":
        return _BLOCK.sub("", text)
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict) and data["mcpServers"].pop(ENTRY, None) is not None:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return text


def _claude_add(secret: str) -> str:
    """One line that pastes the same in PowerShell, cmd and bash: double quotes only, and the
    secret is URL-safe base64. `--transport` keeps `--env` from swallowing the name."""
    command, args = bridge_command()
    if any('"' in part or "%" in part or "$" in part for part in (command, *args)):
        raise ConnectError("The app's install path has characters a pasted command cannot carry safely.")
    quoted = " ".join(f'"{part}"' for part in (command, *args))
    return f"claude mcp add --scope user --env {SECRET_ENV}={secret} --transport stdio {ENTRY} -- {quoted}"


CLAUDE_REMOVE: Final = f"claude mcp remove --scope user {ENTRY}"


def connect(product: str) -> dict[str, Any]:
    label = bridge_registry.PRODUCTS.get(product)
    if label is None:
        raise ConnectError(f"Unknown AI tool: {product!r}.")
    if product == "claude-code":
        _claude_add("x")  # refuse before a secret exists
        secret = bridge_registry.issue(product)
        return {"product": product, "state": "command", "command": _claude_add(secret), "remove_command": CLAUDE_REMOVE}
    path = _config_path(product)
    assert path is not None
    raw = _read(path)
    try:
        original = "" if raw is None else raw.decode("utf-8")
        build = _codex_text if product == "codex" else _gemini_text
        # Build (and encode) with a placeholder first, so a refusal issues no secret at all.
        build(original, "x").encode("utf-8")
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, ConnectError):
            raise
        raise ConnectError("The config file could not be read, so it was left unchanged.") from exc
    previous = bridge_registry.connection(product)
    secret = bridge_registry.issue(product)
    text = build(original, secret)
    backup = None
    if raw is not None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.olga-companion-backup-{stamp}")
        count = 1
        while backup.exists():  # never overwrite an earlier backup
            count += 1
            backup = path.with_name(f"{path.name}.olga-companion-backup-{stamp}-{count}")
        shutil.copy2(path, backup)  # same bytes and permissions as the original
    _write_bytes(path, text.encode("utf-8"))
    # On a second Connect, Remove must still return to the file from before the first one.
    first = previous if previous and previous.get("config_path") == str(path) else None
    bridge_registry.set_connection(
        product,
        {
            "config_path": str(path),
            "written_sha256": _sha(text.encode("utf-8")),
            "existed": first["existed"] if first else raw is not None,
            "original_backup": first["original_backup"] if first else (str(backup) if backup else None),
        },
    )
    return {"product": product, "state": "connected", "path": str(path), "backup": str(backup) if backup else None}


def remove(product: str) -> dict[str, Any]:
    if product not in bridge_registry.PRODUCTS:
        raise ConnectError(f"Unknown AI tool: {product!r}.")
    bridge_registry.revoke(product)
    if product == "claude-code":
        return {"product": product, "state": "command", "command": CLAUDE_REMOVE}
    path = _config_path(product)
    assert path is not None
    record = bridge_registry.connection(product) or {}
    raw = _read(path)
    backup = record.get("original_backup")
    original = _read(Path(backup)) if isinstance(backup, str) else None
    if raw is not None and record.get("written_sha256") == _sha(raw) and (original is not None or record.get("existed") is False):
        # Untouched since Connect: put back exactly what was there (or nothing, if nothing was).
        if original is None:
            path.unlink()
        else:
            _write_bytes(path, original)
    elif raw is not None:
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise ConnectError("The config file could not be read; remove the olga-companion entry by hand.") from exc
        stripped = _without_entry(product, text)
        if stripped != text:
            _write_bytes(path, stripped.encode("utf-8"))
    bridge_registry.set_connection(product, None)
    return {"product": product, "state": "removed", "path": str(path)}


def status() -> list[dict[str, Any]]:
    tools = []
    for product, label in bridge_registry.PRODUCTS.items():
        path = _config_path(product)
        tools.append(
            {
                "product": product,
                "label": label,
                "mode": "file" if path is not None else "command",
                "path": str(path) if path is not None else None,
                "connected": bridge_registry.connected(product),
            }
        )
    return tools
