"""stdio MCP server that runs OLGA Companion's tools in this process, without the desktop app.

The Claude Code plugin starts it with `olga-companion-mcp`. The workspace is the folder Claude
Code runs in (or OLGA_WORKSPACE_DIR), and app state lives in its own folder so it never mixes
with an installed app. It opens no socket: tools run here, and stdout carries protocol only.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Final, TextIO

from . import __version__, config, mcp_bridge

INSTRUCTIONS: Final = (
    "OLGA Companion tools, running on this computer without the desktop app. Read tools answer "
    "directly. Tools that write, run or stop anything ask for your permission first, and a write "
    "always creates a new file: an existing case, table or result is never overwritten."
)


def prepared_env(environ: Mapping[str, str], *, cwd: Path) -> dict[str, str]:
    """The environment the tools read: the workspace and a private state folder, unless set."""
    env = dict(environ)
    env.setdefault("OLGA_WORKSPACE_DIR", str(cwd))
    env.setdefault("OLGA_APP_DATA_DIR", str(config.private_state_root() / "headless"))
    return env


def _answer(payload: Any, *, error: bool = False) -> dict[str, Any]:
    from .sidecar_bridge_routes import _data

    return {"content": [{"type": "text", "text": _data(payload)}], "isError": error}


ASKS_FIRST: Final = "Claude Code asks your permission before this runs."
WRITES: Final = "Writes a new file; nothing existing is overwritten."
# What each gated tool that does not write a file does, in the words of the permission prompt.
EFFECTS: Final = {
    "run_cancel": "Stops a running job.",
    "sweep_cancel": "Stops a running job.",
    "run_execute": "Starts a simulation run on a copy of the case; the case files are not changed.",
    "sweep_execute": "Starts simulation runs on copies of the case; the case files are not changed.",
    "multiflash_open": "Opens the Multiflash program on this computer.",
}
# A plan bundles several writes behind one approval, and its runner needs the app's pending
# store. Here each step is its own tool call, so each write gets its own permission prompt.
NOT_OFFERED: Final = frozenset({"action_plan"})


def _description(name: str, text: str, side_effect: bool) -> str:
    if not side_effect:
        return text
    return f"{text} {EFFECTS.get(name, WRITES)} {ASKS_FIRST}"


def tool_list() -> list[dict[str, Any]]:
    from .agent import tools
    from .sidecar_bridge_routes import HIDDEN_TOOLS

    hidden = set(HIDDEN_TOOLS) | NOT_OFFERED
    if not config.native_tab_enabled():
        hidden |= tools._NATIVE_TAB_TOOLS
    listed = []
    for spec in tools.tool_specs():
        name = spec["name"]
        if name in hidden:
            continue
        side_effect = tools.TOOLS[name].side_effect
        entry: dict[str, Any] = {
            "name": name,
            "title": name.replace("_", " ").capitalize(),
            "description": _description(name, spec["description"], side_effect),
            "inputSchema": spec["parameters"],
            "annotations": {"readOnlyHint": not side_effect},
        }
        if side_effect:
            # Claude Code then asks on every call, whatever the permission mode or allow rules.
            entry["_meta"] = {"anthropic/requiresUserInteraction": True}
        listed.append(entry)
    return listed


DESTINATIONS: Final = ("save_rel", "tab_rel", "mfl_rel", "destination_rel")


def _existing_destination(arguments: dict[str, Any]) -> str | None:
    """The first destination argument that already names a file, before anything is minted.

    Each tool refuses this itself; this second check keeps the promise even if one ever forgets.
    """
    from . import workspace

    names = [arguments.get(key) for key in DESTINATIONS]
    mfl = arguments.get("mfl_rel")
    if isinstance(mfl, str) and mfl and not arguments.get("tab_rel"):
        # fluids_draft_mfl writes its table next to the .mfl when no tab_rel is given.
        names.append(str(Path(mfl).with_suffix(".tab")))
    for value in names:
        if isinstance(value, str) and value and os.path.lexists(workspace.contained(value)):
            return value
    return None


def _approved(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a side-effect tool the harness already asked about: mint, dispatch, never return the token."""
    from . import workspace
    from .agent import approvals, tools

    payload = tools.approval_payload(name, arguments)
    token = approvals.mint(name, payload, context_generation=workspace.context_generation())["token"]
    # 32 URL-safe characters, the shape case_publish requires (as pending_approvals mints them).
    return tools.dispatch(name, {**arguments, "approval_token": token, "idempotency_key": secrets.token_urlsafe(24)})


def _with_saved_path(payload: Any) -> Any:
    """Add where an exported figure or CSV was saved. The app keeps this private; here the user owns the folder."""
    if not isinstance(payload, dict) or not payload.get("artifact_id"):
        return payload
    from . import result_artifacts

    return {**payload, "saved_path": str(result_artifacts.resolve(str(payload["artifact_id"])))}


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from . import genkey_static, workspace
    from .agent import tools
    from .sidecar_bridge_routes import FORBIDDEN_ARGUMENTS

    forged = sorted(FORBIDDEN_ARGUMENTS & set(arguments))
    if forged:
        return _answer({"error": f"Refused: {', '.join(forged)} cannot be sent."}, error=True)
    if name in NOT_OFFERED:
        return _answer({"error": f"{name} is not offered here. Call each step's tool on its own. Nothing ran."}, error=True)
    if name not in {tool["name"] for tool in tool_list()}:
        return _answer({"error": f"Unknown tool: {name}."}, error=True)
    try:
        if tools.TOOLS[name].side_effect:
            existing = _existing_destination(arguments)
            if existing is not None:
                return _answer(
                    {"error": f"{existing} already exists, so nothing was written. Choose a new file name."}, error=True
                )
            return _answer(_approved(name, arguments))
        return _answer(_with_saved_path(tools.dispatch(name, arguments)))
    except (tools.ToolError, workspace.WorkspaceError, genkey_static.OlgaInputError, ValueError) as exc:
        return _answer({"error": str(exc)}, error=True)
    except Exception as exc:  # noqa: BLE001 - one failing tool must not end the server
        print(f"olga-companion-mcp: {name} failed: {exc!r}", file=sys.stderr, flush=True)
        return _answer({"error": f"{name} failed ({type(exc).__name__}). Nothing more was done."}, error=True)


def _post(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
    """The bridge's delivery step, done in this process instead of over loopback."""
    if method == "GET" and path == "/api/bridge/tools":
        return {"tools": tool_list()}
    if method == "POST" and path == "/api/bridge/call" and body is not None:
        return call(body["name"], body["arguments"])
    raise mcp_bridge.BridgeUnavailable(f"Unsupported request: {method} {path}")


def handle(message: Any) -> dict[str, Any] | None:
    if isinstance(message, dict) and message.get("method") == "initialize" and "id" in message:
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "protocolVersion": mcp_bridge.PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "olga-companion", "version": __version__},
                "instructions": INSTRUCTIONS,
            },
        }
    return mcp_bridge.handle(message, _post)


TOOL_WORKERS = 4
# Stops get workers of their own, so a cancel is answered even while every tool worker is busy.
STOPS: Final = frozenset({"run_cancel", "sweep_cancel"})
STOP_WORKERS: Final = 2


def _keyable(request_id: Any) -> bool:
    """JSON-RPC ids are strings or numbers; only those key the pending map."""
    return isinstance(request_id, (str, int, float)) and not isinstance(request_id, bool)


def _is_tool_call(message: Any) -> bool:
    return isinstance(message, dict) and message.get("method") == "tools/call" and _keyable(message.get("id"))


def _tool_name(message: dict[str, Any]) -> Any:
    params = message.get("params")
    return params.get("name") if isinstance(params, dict) else None


def _cancelled_id(message: Any) -> Any:
    if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
        params = message.get("params")
        if isinstance(params, dict) and _keyable(params.get("requestId")):
            return params["requestId"]
    return None


def serve(stdin: TextIO, stdout: TextIO) -> None:
    """Answer on this thread, except tools/call, which runs on a worker.

    A run_patrol poll or a table build can take minutes; ping, tools/list and a run_cancel sent
    meanwhile must still be answered. A call cancelled before a worker picks it up never runs.
    """
    write_lock = threading.Lock()
    pending: dict[Any, Future[None]] = {}
    pending_lock = threading.Lock()

    def reply(response: dict[str, Any] | None) -> None:
        if response is not None:
            with write_lock:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()

    def run(message: dict[str, Any]) -> None:
        try:
            try:
                response = handle(message)
            except Exception as exc:  # noqa: BLE001 - the client must still get an answer for this id
                print(f"olga-companion-mcp: tools/call failed: {exc!r}", file=sys.stderr, flush=True)
                response = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32603, "message": "Internal error."}}
            reply(response)
        except OSError:
            pass  # stdout is closed: the client has gone and there is no one to answer.
        finally:
            with pending_lock:
                pending.pop(message["id"], None)

    with (
        ThreadPoolExecutor(max_workers=TOOL_WORKERS, thread_name_prefix="olga-tool") as workers,
        ThreadPoolExecutor(max_workers=STOP_WORKERS, thread_name_prefix="olga-stop") as stops,
    ):
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error."}})
                continue
            if _is_tool_call(message):
                pool = stops if _tool_name(message) in STOPS else workers
                with pending_lock:
                    pending[message["id"]] = pool.submit(run, message)
                continue
            cancelled = _cancelled_id(message)
            if cancelled is not None:
                with pending_lock:
                    future = pending.get(cancelled)
                if future is not None and future.cancel():
                    with pending_lock:
                        pending.pop(cancelled, None)
                continue
            reply(handle(message))


def _protocol_streams() -> tuple[TextIO, TextIO]:
    """Move the protocol onto private copies of fd 0 and 1, and give fd 0/1 to nobody else.

    A tool's child process inherits fd 0 and 1: from now on fd 0 is empty and fd 1 goes to
    stderr, so a child (or a stray print) can neither eat a request nor corrupt a reply.
    MCP stdio is UTF-8 with one LF per message, whatever the console code page.
    """
    sys.stdout.flush()
    reader = os.fdopen(os.dup(0), "r", encoding="utf-8", newline=None)
    writer = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    os.dup2(2, 1)
    sys.stdin = open(os.devnull, encoding="utf-8")  # noqa: SIM115 - lives as long as the process
    sys.stdout = sys.stderr
    return reader, writer


def main() -> int:
    os.environ.update(prepared_env(os.environ, cwd=Path.cwd()))
    serve(*_protocol_streams())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
