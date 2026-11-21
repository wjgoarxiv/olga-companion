"""stdio MCP server for outside AI tools (`olga-companion-sidecar --mcp`, 0.1.20 P6).

Hand-written JSON-RPC 2.0 over newline-delimited stdin/stdout (the MCP stdio transport):
initialize, tools/list, tools/call, ping. It holds no tools of its own: every call goes to
the running app on loopback with the secret from OLGA_BRIDGE_SECRET, and the app decides.
Nothing here can approve anything.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Final, TextIO

from . import __version__
from .config import SIDECAR_PORT

PROTOCOL_VERSION: Final = "2025-06-18"
SECRET_ENV: Final = "OLGA_BRIDGE_SECRET"
NOT_RUNNING: Final = "OLGA Companion is not running. Open the app, then try again."
TIMEOUT_S: Final = 120

Post = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


class BridgeUnavailable(RuntimeError):
    pass


_DIRECT: Final = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_post(port: str, secret: str) -> Post:
    def call(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-Bridge-Secret": secret},
        )
        try:
            # Loopback only: never through HTTP_PROXY or the system proxy, which would see the secret.
            with _DIRECT.open(request, timeout=TIMEOUT_S) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail")
            except (ValueError, AttributeError):
                detail = None
            raise BridgeUnavailable(str(detail or f"OLGA Companion refused the call (HTTP {exc.code}).")) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise BridgeUnavailable(NOT_RUNNING) from exc

    return call


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message: Any, post: Post) -> dict[str, Any] | None:
    """One JSON-RPC message in, one response out (None for a notification)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request.")
    method = message["method"]
    request_id = message.get("id")
    if "id" not in message:
        return None  # notifications/initialized and friends need no answer
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "olga-companion", "version": __version__},
                "instructions": (
                    "Tools of the OLGA Companion app. Read tools answer directly. Actions that "
                    "write, run or stop anything only ask: the user approves them in the app."
                ),
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        try:
            return _result(request_id, {"tools": post("GET", "/api/bridge/tools", None)["tools"]})
        except BridgeUnavailable as exc:
            return _error(request_id, -32000, str(exc))
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, -32602, "tools/call needs a name and an arguments object.")
        try:
            return _result(request_id, post("POST", "/api/bridge/call", {"name": name, "arguments": arguments}))
        except BridgeUnavailable as exc:
            return _result(request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return _error(request_id, -32601, f"Method not found: {method}")


def serve(stdin: TextIO, stdout: TextIO, post: Post) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = _error(None, -32700, "Parse error.")
        else:
            response = handle(message, post)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> int:
    secret = os.environ.get(SECRET_ENV, "")
    if not secret:
        sys.stderr.write(f"{SECRET_ENV} is not set. Connect this tool again in OLGA Companion Settings.\n")
        return 2
    # MCP stdio is UTF-8 with one LF per message, whatever the console code page (cp949 on
    # Korean Windows crashed on the first non-ASCII tool description).
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n" if stream is sys.stdout else None)
    serve(sys.stdin, sys.stdout, http_post(os.environ.get("OLGA_SIDECAR_PORT", SIDECAR_PORT), secret))
    return 0
