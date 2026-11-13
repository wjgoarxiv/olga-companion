"""xAI (Grok) sign-in for OLGA Companion: the app's own OAuth 2.0 device-code flow.

Mirrors the public device-code protocol used by other xAI-integrated tools, but the
app keeps its own credentials in ``~/.olga_copilot/xai_tokens.json`` (0600) and never reads
any other tool's credential files.

Secrets policy: access/refresh tokens and the device_code never leave this module through
status, return values, logs or error text. user_code and the verification URL are meant to
be shown to the operator.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .codex_oauth_lock import InterprocessRefreshLock
from .openai_responses_adapter import OpenAIResponsesApiClient

logger = logging.getLogger(__name__)

AUTH_BASE = "https://auth.x.ai/oauth2"
API_BASE = "https://api.x.ai/v1"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
REFERRER = "olga-companion"
USER_AGENT = "OLGA-Companion/1.0 (xai-oauth)"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_WINDOW_SECONDS = 5 * 60
DEFAULT_INTERVAL = 5
DEFAULT_LOGIN_TTL = 900

TOKENS_FILE = Path.home() / ".olga_copilot" / "xai_tokens.json"

MSG_NOT_CONNECTED = "xAI 계정이 연결되지 않았습니다. 설정에서 xAI를 연결하세요."
MSG_AUTH_FAILED = "xAI 인증이 거부되었습니다. xAI를 다시 연결하세요."
MSG_FORBIDDEN = (
    "xAI가 이 요청을 거부했습니다(403). 현재 구독 등급에서는 외부 앱 OAuth를 지원하지 않을 수 있습니다. "
    "xAI를 다시 연결하거나 다른 공급자를 사용하세요."
)
MSG_VERSION = "xAI가 이 앱의 클라이언트 버전을 거부했습니다(426). 앱을 최신 버전으로 업데이트하세요."
_STATE_MESSAGES = {
    "idle": "xAI 계정이 연결되지 않았습니다.",
    "pending": "브라우저에서 코드를 확인하고 승인하세요.",
    "connected": "xAI에 연결되었습니다.",
    "denied": "승인이 거부되었습니다. 다시 연결하세요.",
    "expired": "코드가 만료되었습니다. 다시 연결하세요.",
}


class XaiAuthError(RuntimeError):
    """Operator-safe (Korean, token-free) xAI auth failure."""


# ---- HTTP seam (replaced in tests) -----------------------------------------------------------------

def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _http_request(
    method: str,
    url: str,
    *,
    form: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    """Return (status, parsed JSON object or {}). Network failures raise XaiAuthError."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        raise XaiAuthError("xAI 서버에 연결하지 못했습니다. 네트워크를 확인하세요.") from None
    try:
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def _form_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


# ---- token store ------------------------------------------------------------------------------------

def _read_tokens() -> dict[str, Any] | None:
    try:
        data = json.loads(Path(TOKENS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("access_token"), str) or not isinstance(data.get("refresh_token"), str):
        return None
    if not data["access_token"] or not data["refresh_token"]:
        return None
    return data


def _write_tokens(tokens: dict[str, Any]) -> None:
    """Atomic 0600 write: temp file in the same directory, fsync, os.replace."""
    path = Path(TOKENS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".xai_tokens.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(tokens))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _delete_tokens() -> None:
    try:
        Path(TOKENS_FILE).unlink()
    except OSError:
        pass


def _jwt_exp(token: str) -> float | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = payload.get("exp")
    except (ValueError, AttributeError):
        return None
    return float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None


def _expires_at(body: dict[str, Any]) -> float:
    expires_in = body.get("expires_in")
    if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool) and expires_in > 0:
        return time.time() + float(expires_in)
    return _jwt_exp(str(body.get("access_token", ""))) or time.time() + 3600


def _tokens_from_response(body: dict[str, Any], previous_refresh: str | None = None) -> dict[str, Any]:
    access = body.get("access_token")
    refresh = body.get("refresh_token") or previous_refresh
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise XaiAuthError("xAI 응답에 갱신 토큰이 없어 연결할 수 없습니다. 다시 시도하세요.")
    return {"access_token": access, "refresh_token": refresh, "expires_at": _expires_at(body)}


# ---- refresh (single-flight) ------------------------------------------------------------------------

_refresh_lock = threading.Lock()


def _lock_path() -> Path:
    path = Path(TOKENS_FILE)
    return path.with_name(path.name + ".lock")


def _needs_refresh(tokens: dict[str, Any], stale_token: str | None) -> bool:
    if stale_token is not None and tokens["access_token"] == stale_token:
        return True
    return float(tokens.get("expires_at", 0)) - time.time() <= REFRESH_WINDOW_SECONDS


def get_fresh_access_token(*, stale_token: str | None = None) -> str:
    """Return a usable access token, refreshing when within 5 minutes of expiry.

    `stale_token`: a token the server just rejected (401); it is refreshed unless another
    caller already rotated it. Refresh tokens rotate, so exactly one refresh may be in
    flight: an in-process lock plus the cross-process file lock, re-reading the store after
    acquiring them."""
    tokens = _read_tokens()
    if tokens is None:
        raise XaiAuthError(MSG_NOT_CONNECTED)
    if not _needs_refresh(tokens, stale_token):
        return tokens["access_token"]
    with _refresh_lock, InterprocessRefreshLock(_lock_path()):
        tokens = _read_tokens()
        if tokens is None:
            raise XaiAuthError(MSG_NOT_CONNECTED)
        if not _needs_refresh(tokens, stale_token):
            return tokens["access_token"]
        status, body = _http_request(
            "POST",
            f"{AUTH_BASE}/token",
            form={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CLIENT_ID,
            },
            headers=_form_headers(),
        )
        if status != 200:
            if body.get("error") == "invalid_grant":
                _delete_tokens()
                _clear_models_cache()
                raise XaiAuthError("xAI 로그인이 만료되었습니다. xAI를 다시 연결하세요.")
            raise XaiAuthError("xAI 토큰을 갱신하지 못했습니다. 잠시 후 다시 시도하세요.")
        fresh = _tokens_from_response(body, previous_refresh=tokens["refresh_token"])
        _write_tokens(fresh)
        return fresh["access_token"]


# ---- device-code login ------------------------------------------------------------------------------

_state_lock = threading.Lock()
_state: dict[str, Any] = {"state": "idle", "message": "", "generation": 0}


def _reset_for_tests() -> None:
    with _state_lock:
        generation = _state["generation"] + 1
        _state.clear()
        _state.update({"state": "idle", "message": "", "generation": generation})
    _clear_models_cache()


def _poll_interval(device: dict[str, Any]) -> int:
    value = device.get("interval")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(1, int(value))
    return DEFAULT_INTERVAL


def _set_terminal(generation: int, state: str, message: str | None = None) -> None:
    with _state_lock:
        if _state["generation"] != generation:
            return
        _state.update({"state": state, "message": message or _STATE_MESSAGES.get(state, "")})


def start_login() -> dict[str, Any]:
    """Start the device flow; poll in a background thread. Returns only public fields."""
    status, device = _http_request(
        "POST",
        f"{AUTH_BASE}/device/code",
        form={"client_id": CLIENT_ID, "scope": SCOPE, "referrer": REFERRER},
        headers=_form_headers(),
    )
    needed = ("device_code", "user_code", "verification_uri")
    if status != 200 or not all(isinstance(device.get(k), str) and device[k] for k in needed):
        raise XaiAuthError("xAI 로그인을 시작하지 못했습니다. 잠시 후 다시 시도하세요.")
    ttl = device.get("expires_in")
    ttl = float(ttl) if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) and ttl > 0 else DEFAULT_LOGIN_TTL
    expires_at = time.time() + ttl
    public = {
        "user_code": device["user_code"],
        "verification_uri": device["verification_uri"],
        "verification_uri_complete": device.get("verification_uri_complete") or device["verification_uri"],
        "expires_at": expires_at,
    }
    with _state_lock:
        generation = _state["generation"] + 1
        _state.clear()
        _state.update({"state": "pending", "message": _STATE_MESSAGES["pending"], "generation": generation, **public})
    threading.Thread(
        target=_poll_login,
        args=(generation, device["device_code"], _poll_interval(device), expires_at),
        name="xai-oauth-poll",
        daemon=True,
    ).start()
    return public


def _poll_login(generation: int, device_code: str, interval: int, expires_at: float) -> None:
    try:
        while time.time() < expires_at:
            with _state_lock:
                if _state["generation"] != generation:
                    return
            status, body = _http_request(
                "POST",
                f"{AUTH_BASE}/token",
                form={"grant_type": DEVICE_GRANT, "client_id": CLIENT_ID, "device_code": device_code},
                headers=_form_headers(),
            )
            if status == 200:
                _finish_login(generation, body)
                return
            error = body.get("error")
            if error == "slow_down":
                interval += 5
            elif error in ("access_denied", "authorization_denied"):
                _set_terminal(generation, "denied")
                return
            elif error == "expired_token":
                _set_terminal(generation, "expired")
                return
            elif error != "authorization_pending":
                _set_terminal(generation, "error", "xAI 로그인에 실패했습니다. 다시 시도하세요.")
                return
            _sleep(interval)
        _set_terminal(generation, "expired")
    except XaiAuthError as exc:
        _set_terminal(generation, "error", str(exc))
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — never leak details into status
        logger.warning("xai login polling failed")
        _set_terminal(generation, "error", "xAI 로그인 중 오류가 발생했습니다. 다시 시도하세요.")


def _finish_login(generation: int, body: dict[str, Any]) -> None:
    try:
        tokens = _tokens_from_response(body)
    except XaiAuthError as exc:
        _set_terminal(generation, "error", str(exc))
        return
    with _state_lock:
        if _state["generation"] != generation:
            return
        with _refresh_lock:
            _write_tokens(tokens)
        _state.clear()
        _state.update({"state": "connected", "message": _STATE_MESSAGES["connected"], "generation": generation})
    _clear_models_cache()
    try:
        list_chat_models()  # warm the model list so the picker is populated right away
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — best-effort warm-up
        pass


def login_status() -> dict[str, Any]:
    """Public login state. Never contains tokens or the device_code."""
    with _state_lock:
        snapshot = dict(_state)
    state = snapshot["state"]
    if state in ("idle", "connected"):
        state = "connected" if _read_tokens() is not None else "idle"
        return {"state": state, "message": _STATE_MESSAGES[state]}
    out = {"state": state, "message": snapshot.get("message") or _STATE_MESSAGES.get(state, "")}
    if state == "pending":
        for key in ("user_code", "verification_uri", "verification_uri_complete", "expires_at"):
            out[key] = snapshot.get(key)
    return out


def logout() -> dict[str, Any]:
    with _state_lock:
        generation = _state["generation"] + 1
        _state.clear()
        _state.update({"state": "idle", "message": "", "generation": generation})
    with _refresh_lock:
        _delete_tokens()
    _clear_models_cache()
    return login_status()


# ---- models (live, never hardcoded) -----------------------------------------------------------------

_MODELS_CACHE: dict[str, Any] = {}


def _clear_models_cache() -> None:
    _MODELS_CACHE.clear()


def _chat_model(item: object) -> dict[str, str] | None:
    """Keep a language-model row only when its documented output is text alone."""
    if not isinstance(item, dict):
        return None
    model_id = item.get("id")
    outputs = item.get("output_modalities")
    if not isinstance(model_id, str) or not model_id or not isinstance(outputs, list):
        return None
    if "text" not in outputs or "image" in outputs or "video" in outputs:
        return None
    return {"id": model_id, "label": model_id, "tier": "standard"}


def _fetch_models() -> list[dict[str, str]] | None:
    token = get_fresh_access_token()
    for attempt in range(2):
        status, body = _http_request(
            "GET",
            f"{API_BASE}/language-models",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": USER_AGENT},
        )
        if status == 401 and attempt == 0:
            token = get_fresh_access_token(stale_token=token)
            continue
        if status != 200 or not isinstance(body, dict):
            return None
        items = body.get("models")
        if not isinstance(items, list):
            return None
        return [model for item in items if (model := _chat_model(item)) is not None]
    return None


def _warm_models_cache() -> None:
    try:
        models = _fetch_models()
        if models is not None:
            _MODELS_CACHE.update({"models": models, "at": time.time()})
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — fail-soft
        pass
    finally:
        _MODELS_CACHE["refreshing"] = False


def list_chat_models(*, ttl: float = 600.0, cache_only: bool = False) -> list[dict[str, str]]:
    """Live model list for the signed-in account; [] when disconnected or on any error."""
    if _read_tokens() is None:
        return []
    cached = _MODELS_CACHE.get("models")
    if cached is not None and (time.time() - float(_MODELS_CACHE.get("at", 0.0))) < ttl:
        return cached
    if cache_only:
        if not _MODELS_CACHE.get("refreshing"):
            _MODELS_CACHE["refreshing"] = True
            threading.Thread(target=_warm_models_cache, daemon=True).start()
        return cached or []
    try:
        models = _fetch_models()
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — fail-soft
        models = None
    if models is None:
        return cached or []
    _MODELS_CACHE.update({"models": models, "at": time.time()})
    return models


# ---- inference client -------------------------------------------------------------------------------

class XaiResponsesApiClient(OpenAIResponsesApiClient):
    """OpenAI-compatible Responses client for api.x.ai with token refresh and error mapping."""

    def __init__(self, access_token: str) -> None:
        super().__init__(base_url=API_BASE, access_token=access_token)

    async def stream_generate(self, **kwargs: Any) -> Any:
        try:
            self._access_token = await asyncio.to_thread(get_fresh_access_token)
            refreshed = False
            while True:
                try:
                    return await super().stream_generate(**kwargs)
                except ValueError as exc:
                    text = str(exc)
                    if "(401)" in text:
                        if refreshed:
                            raise ValueError(MSG_AUTH_FAILED) from None
                        refreshed = True
                        self._access_token = await asyncio.to_thread(
                            lambda: get_fresh_access_token(stale_token=self._access_token)
                        )
                        continue
                    if "(403)" in text:
                        raise ValueError(MSG_FORBIDDEN) from None
                    if "error 426" in text:
                        raise ValueError(MSG_VERSION) from None
                    raise
        except XaiAuthError as exc:
            raise ValueError(str(exc)) from None


def build_responses_client() -> OpenAIResponsesApiClient:
    """Tool-calling client for the agent runtime. Raises XaiAuthError when not connected."""
    return XaiResponsesApiClient(get_fresh_access_token())


def build_text_client(model: str) -> Callable[..., str]:
    """Simple `(*, system_prompt, user_prompt) -> str` client over the same Responses API."""

    def call(*, system_prompt: str, user_prompt: str, **_: Any) -> str:
        client = build_responses_client()

        async def run() -> str:
            conversation = client.create_conversation(model)
            conversation.add_user_message(user_prompt)
            result = await client.stream_generate(
                conversation=conversation, model=model, system_instruction=system_prompt
            )
            return result.text

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(run())
        box: dict[str, Any] = {}
        worker = threading.Thread(target=lambda: box.update(text=asyncio.run(run())), daemon=True)
        worker.start()
        worker.join()
        return str(box.get("text", ""))

    return call
