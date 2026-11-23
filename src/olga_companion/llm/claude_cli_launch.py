"""The environment and the per-turn private files a CLI chat turn is started with.

The user's own sign-in stays where the CLI keeps it: the profile variables pass through
untouched and nothing under the user's Claude folders is read. Everything that belongs to this
app (``OLGA_*``) is dropped. The bridge secret and port live only in a per-turn MCP config inside
a private folder that is deleted when the turn ends.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .. import config, windows_native_launch
from ..ai_tool_connect import ENTRY, bridge_command
from ..mcp_bridge import SECRET_ENV
from .codex_oauth_privacy import harden_private_path

PORT_ENV = "OLGA_SIDECAR_PORT"
STALE_AFTER_S = 3600.0
_LOOPBACK = "127.0.0.1,localhost,::1"


class LaunchError(RuntimeError):
    """The private run folder could not be prepared, so the CLI is not started."""


@dataclass(frozen=True)
class RunFiles:
    run_dir: Path
    mcp_config: Path


def run_root() -> Path:
    return config.private_state_root() / "claude-cli"


def build_env(environ: Mapping[str, str], *, bundle_dir: str | None, proxy: str | None) -> dict[str, str]:
    env = windows_native_launch.child_environment(environ, bundle_dir)
    env = {k: v for k, v in env.items() if not k.upper().startswith("OLGA_")}
    if proxy:
        env["HTTPS_PROXY"] = env["HTTP_PROXY"] = proxy
        env["https_proxy"] = env["http_proxy"] = proxy
        env["NO_PROXY"] = env["no_proxy"] = _LOOPBACK
    return env


def default_env() -> dict[str, str]:
    import os

    from ..net.http import proxy_url

    return build_env(os.environ, bundle_dir=getattr(sys, "_MEIPASS", None), proxy=proxy_url())


@contextmanager
def run_files(
    secret: str,
    port: int,
    *,
    root: Path | None = None,
    harden: Callable[..., None] | None = None,
    with_tools: bool = True,
) -> Iterator[RunFiles]:
    base = run_root() if root is None else root
    harden = harden_private_path if harden is None else harden
    run_dir = base / f"run-{uuid.uuid4().hex}"
    try:
        run_dir.mkdir(parents=True)
        harden(run_dir, directory=True)
    except OSError as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise LaunchError("The private folder for this chat turn could not be prepared.") from exc
    try:
        command, args = bridge_command()
        mcp_config = run_dir / "mcp.json"
        servers = {ENTRY: {"command": command, "args": args,
                           "env": {SECRET_ENV: secret, PORT_ENV: str(port)}}} if with_tools else {}
        payload = {"mcpServers": servers}
        try:
            mcp_config.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            raise LaunchError("The settings file for this chat turn could not be written.") from exc
        yield RunFiles(run_dir=run_dir, mcp_config=mcp_config)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@asynccontextmanager
async def run_files_async(secret: str, port: int, **kwargs: object) -> AsyncIterator[RunFiles]:
    """:func:`run_files` with the folder hardening and removal kept off the event loop."""
    files = run_files(secret, port, **kwargs)  # type: ignore[arg-type]
    entered = await asyncio.to_thread(files.__enter__)
    try:
        yield entered
    finally:
        await asyncio.to_thread(files.__exit__, None, None, None)


def sweep_stale(*, root: Path | None = None, now: float | None = None) -> None:
    """Remove run folders a crashed sidecar left behind."""
    base = run_root() if root is None else root
    cutoff = (time.time() if now is None else now) - STALE_AFTER_S
    try:
        entries = list(base.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir() and entry.name.startswith("run-") and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue
