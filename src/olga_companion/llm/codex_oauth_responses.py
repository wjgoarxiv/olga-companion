"""Synchronous Responses SSE transport for the Codex OAuth provider."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .codex_oauth_models import CodexAuthError, CodexCredentials

ResponseBody = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ResponseBindings:
    """Transport seams resolved by the facade for compatibility testing."""

    endpoint: str
    client_factory: Callable[..., httpx.Client]
    mark_auth_failure: Callable[[], None]
    extract_text: Callable[[dict[str, Any]], str]


def collect_output_text(output: Any) -> str:
    """Concatenate every visible output-text part in a response envelope."""
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "".join(chunks)


def extract_text_from_event(
    payload: dict[str, Any],
    *,
    collect_output: Callable[[Any], str] = collect_output_text,
) -> str:
    """Extract operator-visible text from one Responses SSE event."""
    event_type = payload.get("type", "")
    if event_type == "response.output_text.delta":
        delta = payload.get("delta")
        return delta if isinstance(delta, str) else ""
    if event_type in ("response.completed", "response.output_text.done"):
        if event_type == "response.output_text.done":
            text = payload.get("text")
            return text if isinstance(text, str) else ""
        response = payload.get("response")
        if isinstance(response, dict):
            return collect_output(response.get("output"))
    return ""


def request_headers(creds: CodexCredentials) -> dict[str, str]:
    """Build the authenticated Codex Responses request headers."""
    return {
        "Authorization": f"Bearer {creds.access_token}",
        "chatgpt-account-id": creds.account_id or "",
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "session_id": str(uuid.uuid4()),
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }


def request_body(
    *,
    model: str,
    config: dict[str, str],
    system_prompt: str,
    user_prompt: str,
) -> ResponseBody:
    """Build the non-tool Codex Responses request body."""
    return {
        "model": model,
        "reasoning": {
            "effort": config["reasoning.effort"],
            "summary": config["reasoning.summary"],
        },
        "text": {"verbosity": config["text.verbosity"]},
        "instructions": system_prompt,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            }
        ],
        "store": False,
        "stream": True,
    }


def call_model(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    config: dict[str, str],
    creds: CodexCredentials,
    bindings: ResponseBindings,
    on_delta: Callable[[str], None] | None,
    on_reasoning_delta: Callable[[str], None] | None,
    timeout: float,
) -> str:
    """Consume a synchronous Responses stream and return visible output."""
    if not creds.account_id:
        raise CodexAuthError(
            "codex 계정 정보를 확인할 수 없습니다. 다시 로그인해 주세요.",
            relogin_required=True,
        )
    headers = request_headers(creds)
    body = request_body(
        model=model,
        config=config,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    deltas: list[str] = []
    final_text = ""
    try:
        with bindings.client_factory(timeout=timeout) as client:
            with client.stream(
                "POST", bindings.endpoint, json=body, headers=headers
            ) as response:
                _raise_for_status(response, bindings.mark_auth_failure)
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except (json.JSONDecodeError, RecursionError, ValueError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") == "response.reasoning_summary_text.delta":
                        _emit_reasoning(event, on_reasoning_delta)
                        continue
                    text = bindings.extract_text(event)
                    if not text:
                        continue
                    if event.get("type") == "response.output_text.delta":
                        deltas.append(text)
                        _emit(text, on_delta)
                    else:
                        final_text = text
    except CodexAuthError:
        raise
    except httpx.HTTPError as exc:
        raise CodexAuthError(
            f"codex 모델 호출 네트워크 오류: {type(exc).__name__}"
        ) from None
    text = ("".join(deltas) or final_text).strip()
    if on_delta is not None and not deltas and text:
        _emit(text, on_delta)
    return text


def _raise_for_status(response: httpx.Response, mark_auth_failure: Callable[[], None]) -> None:
    if response.status_code == 401:
        mark_auth_failure()
        raise CodexAuthError(
            "codex 인증이 만료되었습니다. 다시 로그인해 주세요.",
            relogin_required=True,
        )
    if response.status_code == 429:
        raise CodexAuthError("codex 사용량 한도에 도달했습니다. 잠시 후 다시 시도하세요.")
    if response.status_code >= 400:
        response.read()
        raise CodexAuthError(f"codex 모델 호출 실패 (HTTP {response.status_code})")


def _emit(text: str, callback: Callable[[str], None] | None) -> None:
    if callback is None:
        return
    try:
        callback(text)
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        return


def _emit_reasoning(
    event: dict[str, Any], callback: Callable[[str], None] | None
) -> None:
    delta = event.get("delta")
    if isinstance(delta, str) and delta:
        _emit(delta, callback)
