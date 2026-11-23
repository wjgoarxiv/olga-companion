"""Turn the CLI's ``--output-format stream-json`` lines into chat events, and failures into one code.

Only structured fields decide a failure: the ``result`` event's ``is_error`` and
``api_error_status``, the CLI-made assistant message (``is_api_error_message``) and its
``error`` value, and ``rate_limit_event``. Model-written text never does, so a reply that
merely says "Not logged in" stays a reply. The session id and raw stderr are never kept.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..agent.runtime import AgentEvent, _sanitize_failure_text
from . import provider_runtime_status

PROVIDER = "claude_cli"
SERVER = "olga-companion"
TOOL_PREFIX = f"mcp__{SERVER}__"
TOOL_RESULT_CHARS = 20_000
DETAIL_CHARS = 200
_DATA_FENCE = re.compile(
    r"^\s*<<<OLGA DATA \(output from OLGA Companion, not instructions\)\n(.*)\nOLGA DATA>>>\s*$", re.DOTALL
)
_NETWORK = re.compile(
    r"ECONNREFUSED|ENOTFOUND|ETIMEDOUT|ECONNRESET|EAI_AGAIN|getaddrinfo|proxy|certificate|"
    r"SELF_SIGNED|UNABLE_TO_GET_ISSUER|issuer certificate|Connection error|socket hang up",
    re.IGNORECASE,
)

_TEXT: dict[str, tuple[str, str]] = {
    "not_logged_in": (
        "Claude Code에 로그인되어 있지 않습니다. 터미널에서 `claude`를 실행해 로그인한 뒤 다시 시도하세요. "
        "이 앱은 로그인 정보를 묻거나 보지 않습니다.",
        "Claude Code is not signed in. Run `claude` in a terminal, sign in, then try again. "
        "This app never asks for or sees your sign-in.",
    ),
    "login_expired": (
        "Claude Code 로그인이 만료되었습니다. 터미널에서 `claude`를 실행해 다시 로그인한 뒤 시도하세요. "
        "이 앱은 로그인 정보를 묻거나 보지 않습니다.",
        "Your Claude Code sign-in has expired. Run `claude` in a terminal, sign in again, then retry. "
        "This app never asks for or sees your sign-in.",
    ),
    "rate_limited": (
        "Claude Code 사용 한도에 도달했습니다. 한도가 풀린 뒤 다시 시도하세요.",
        "Claude Code has reached its usage limit. Try again after the limit resets.",
    ),
    "org_policy": (
        "조직 정책 때문에 Claude Code 요청이 거부되었습니다. 조직 관리자에게 문의하세요.",
        "Your organization's policy refused this Claude Code request. Ask your administrator.",
    ),
    "network": (
        "Claude Code가 인터넷에 연결하지 못했습니다. 네트워크나 프록시를 확인하세요 (설정 → 네트워크).",
        "Claude Code could not reach the internet. Check your network or proxy (Settings → Network).",
    ),
    "timeout": (
        "Claude Code가 제시간에 응답하지 않아 중단했습니다. 다시 시도하세요.",
        "Claude Code did not answer in time, so the turn was stopped. Try again.",
    ),
    "cancelled": ("요청을 취소했습니다.", "The request was cancelled."),
    "crashed": (
        "Claude Code가 예기치 않게 종료되었습니다. 다시 시도하고, 계속되면 `claude --version`으로 설치를 확인하세요.",
        "Claude Code stopped unexpectedly. Try again; if it keeps happening, check the install with `claude --version`.",
    ),
    "output_too_large": (
        "Claude Code의 응답이 너무 커서 중단했습니다. 질문을 좁혀 다시 시도하세요.",
        "Claude Code's reply was too large, so the turn was stopped. Ask a narrower question.",
    ),
    "bad_output": (
        "Claude Code의 출력을 읽지 못했습니다. Claude Code를 최신 버전으로 업데이트한 뒤 다시 시도하세요.",
        "Claude Code's output could not be read. Update Claude Code, then try again.",
    ),
    "isolation_failed": (
        "Claude Code가 이 앱의 도구 외에 다른 도구를 쓰려 해서 안전을 위해 중단했습니다.",
        "Claude Code tried to use a tool other than this app's, so the turn was stopped for safety.",
    ),
    "tools_unavailable": (
        "이 앱의 도구를 시작하지 못해 대화를 멈췄습니다. 앱을 다시 시작한 뒤 다시 시도하세요. 계속되면 보안 프로그램이 앱을 막고 있는지 확인하세요.",
        "The app's tools could not start, so the turn was stopped. Restart the app and try again; if it keeps happening, check whether security software blocks the app.",
    ),
    "unknown": (
        "Claude Code에서 오류가 났습니다.",
        "Claude Code reported an error.",
    ),
}
CODES: tuple[str, ...] = tuple(_TEXT)


def message(code: str, locale: str) -> str:
    ko, en = _TEXT.get(code, _TEXT["unknown"])
    return ko if locale == "ko" else en


class ClaudeCliError(Exception):
    def __init__(self, code: str, detail: str = "", *, resets_at: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = _sanitize_failure_text(detail, DETAIL_CHARS) if detail else ""
        self.resets_at = resets_at

    def text(self, locale: str) -> str:
        base = message(self.code, locale)
        return f"{base} ({self.detail})" if self.code == "unknown" and self.detail else base


def _epoch(value: Any) -> float | None:
    """``credential_expires_at`` as seconds; the CLI writes an ISO time, older builds a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e11 else float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict) and c.get("type") == "text")
    else:
        text = ""
    fenced = _DATA_FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    if len(text) > TOOL_RESULT_CHARS:
        text = text[:TOOL_RESULT_CHARS] + "\n… (cut)"
    return text


def _result_value(content: Any, is_error: bool) -> dict[str, Any]:
    """The tool's own result dict when the bridge sent one, as the in-app runtime yields it."""
    text = _result_text(content)
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, dict):
        if is_error and "error" not in value:
            value = {**value, "error": text}
        return value
    return {"error": text} if is_error else {"text": text}


class StreamParser:
    """Feed lines in order with :meth:`feed`, then call :meth:`finish` once the process exits."""

    def __init__(self, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self.version = ""
        self.api_key_source = ""
        self.denied: list[str] = []
        self._valid = 0
        self._init_seen = False
        self._names: dict[str, str] = {}
        self._result: dict[str, Any] | None = None
        self._api_error = ""
        self._rate_reset: int | None = None
        self._rate_rejected = False

    def feed(self, line: str) -> list[AgentEvent]:
        try:
            event = json.loads(line)
        except ValueError:
            return []
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            return []
        kind = event["type"]
        if kind == "system":
            return self._system(event)
        if kind == "assistant":
            return self._assistant(event)
        if kind == "user":
            return self._user(event)
        if kind == "result":
            self._valid += 1
            self._result = event
            return []
        if kind == "rate_limit_event":
            self._valid += 1
            info = event.get("rate_limit_info") or {}
            if isinstance(info.get("resetsAt"), int):
                self._rate_reset = info["resetsAt"]
            if info.get("status") == "rejected":
                self._rate_rejected = True
            return []
        return []

    def _require_init(self) -> None:
        if not self._init_seen:
            raise ClaudeCliError("isolation_failed", "event before init")

    def _system(self, event: dict[str, Any]) -> list[AgentEvent]:
        self._valid += 1
        if event.get("subtype") == "init":
            tools = event.get("tools") or []
            servers = event.get("mcp_servers") or []
            if any(not str(t).startswith(TOOL_PREFIX) for t in tools):
                raise ClaudeCliError("isolation_failed", "tool outside this app")
            if any(not isinstance(s, dict) or s.get("name") != SERVER for s in servers):
                raise ClaudeCliError("isolation_failed", "server outside this app")
            if any(s.get("status") == "failed" for s in servers):
                raise ClaudeCliError("tools_unavailable", "the app's MCP server did not start")
            self.version = str(event.get("claude_code_version") or "")
            self.api_key_source = str(event.get("apiKeySource") or "")
            self._init_seen = True
        elif event.get("subtype") == "permission_denied":
            name = str(event.get("tool_name") or "")
            self.denied.append(name.removeprefix(TOOL_PREFIX))
        return []

    def _assistant(self, event: dict[str, Any]) -> list[AgentEvent]:
        self._valid += 1
        self._require_init()
        if event.get("is_api_error_message"):
            self._api_error = str(event.get("error") or "unknown")
            return []
        out: list[AgentEvent] = []
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                out.append(AgentEvent("text", {"text": str(block["text"])}))
            elif block.get("type") == "tool_use":
                name = str(block.get("name") or "")
                if not name.startswith(TOOL_PREFIX):
                    raise ClaudeCliError("isolation_failed", "tool outside this app")
                short = name.removeprefix(TOOL_PREFIX)
                call_id = str(block.get("id") or "")
                self._names[call_id] = short
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                out.append(AgentEvent("tool_call", {"name": short, "args": args, "call_id": call_id}))
        return out

    def _user(self, event: dict[str, Any]) -> list[AgentEvent]:
        self._valid += 1
        self._require_init()
        out: list[AgentEvent] = []
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                call_id = str(block.get("tool_use_id") or "")
                data: dict[str, Any] = {"name": self._names.get(call_id, ""), "call_id": call_id,
                                        "result": _result_value(block.get("content"), bool(block.get("is_error")))}
                if block.get("is_error"):
                    data["is_error"] = True
                out.append(AgentEvent("tool_result", data))
        return out

    def finish(self, *, returncode: int | None, stderr_tail: str) -> list[AgentEvent]:
        result = self._result
        if result is not None and not result.get("is_error") and not self._api_error:
            provider_runtime_status.clear(PROVIDER)
            return [AgentEvent("done", {"text": str(result.get("result") or "")})]
        error = self._classify(result, returncode, stderr_tail)
        if error.code in ("not_logged_in", "login_expired"):
            provider_runtime_status.record_auth_failure(PROVIDER)
        raise error

    def _classify(self, result: dict[str, Any] | None, returncode: int | None, stderr: str) -> ClaudeCliError:
        if result is None:
            if self._valid == 0:
                return ClaudeCliError("bad_output", stderr)
            if _NETWORK.search(stderr):
                return ClaudeCliError("network")
            return ClaudeCliError("crashed", f"exit {returncode}")
        text = str(result.get("result") or "")
        status = result.get("api_error_status")
        expires = result.get("credential_expires_at")
        if self._api_error == "authentication_failed" or status == 401:
            return ClaudeCliError("not_logged_in" if text.startswith("Not logged in") else "login_expired")
        expiry = _epoch(expires)
        if expiry is not None and expiry < self._now():
            return ClaudeCliError("login_expired")
        if status == 429 or self._api_error == "rate_limit" or self._rate_rejected:
            return ClaudeCliError("rate_limited", resets_at=self._rate_reset)
        if status == 403:
            return ClaudeCliError("org_policy")
        if _NETWORK.search(text) or _NETWORK.search(stderr):
            return ClaudeCliError("network")
        return ClaudeCliError("unknown", text or stderr)
