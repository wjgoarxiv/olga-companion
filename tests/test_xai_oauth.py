"""xAI (Grok) device-code OAuth: protocol, token store, refresh and inference error mapping.

No real network: `xai_oauth._http_request` and `xai_oauth._sleep` are replaced.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import threading
import time

import pytest

from olga_companion.llm import xai_oauth
from olga_companion.llm.openai_responses_adapter import OpenAIResponsesApiClient

SECRETS = ("AT-secret", "RT-secret", "DEV-secret", "RT-rotated", "AT-rotated")
DEVICE = {
    "device_code": "DEV-secret",
    "user_code": "ABCD-1234",
    "verification_uri": "https://accounts.x.ai/device",
    "verification_uri_complete": "https://accounts.x.ai/device?user_code=ABCD-1234",
    "expires_in": 600,
    "interval": 5,
}


class FakeHttp:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, method, url, *, form=None, headers=None, timeout=30.0):
        with self.lock:
            self.calls.append({"method": method, "url": url, "form": form, "headers": headers or {}})
        return self.handler(method, url, form or {}, headers or {})

    def token_calls(self, grant):
        return [c for c in self.calls if c["url"].endswith("/token") and c["form"].get("grant_type", "").endswith(grant)]


@pytest.fixture(autouse=True)
def sleeps(tmp_path, monkeypatch):
    recorded: list[float] = []

    def fake_sleep(seconds):
        recorded.append(seconds)
        time.sleep(0.002)

    monkeypatch.setattr(xai_oauth, "TOKENS_FILE", tmp_path / "xai_tokens.json")
    monkeypatch.setattr(xai_oauth, "_sleep", fake_sleep)
    xai_oauth._reset_for_tests()
    yield recorded
    xai_oauth._reset_for_tests()


def install(monkeypatch, handler) -> FakeHttp:
    fake = FakeHttp(handler)
    monkeypatch.setattr(xai_oauth, "_http_request", fake)
    return fake


def ok_token(**extra):
    return (200, {"access_token": "AT-secret", "refresh_token": "RT-secret", "expires_in": 3600, **extra})


def wait_state(target, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = xai_oauth.login_status()
        if st["state"] == target:
            return st
        time.sleep(0.005)
    raise AssertionError(f"never reached {target}: {xai_oauth.login_status()}")


def device_handler(token_responses):
    queue = list(token_responses)

    def handler(method, url, form, headers):
        if url.endswith("/device/code"):
            return 200, dict(DEVICE)
        if url.endswith("/token"):
            return queue.pop(0) if len(queue) > 1 else queue[0]
        raise AssertionError(url)

    return handler


def write_tokens(expires_in, access="AT-secret", refresh="RT-secret"):
    xai_oauth._write_tokens(
        {"access_token": access, "refresh_token": refresh, "expires_at": time.time() + expires_in}
    )


# ---- device start -------------------------------------------------------------------------------

def test_start_login_request_shape_and_public_return(monkeypatch):
    fake = install(monkeypatch, device_handler([(400, {"error": "authorization_pending"})]))
    out = xai_oauth.start_login()
    assert set(out) == {"user_code", "verification_uri", "verification_uri_complete", "expires_at"}
    assert out["user_code"] == "ABCD-1234"
    assert out["verification_uri_complete"].endswith("ABCD-1234")
    start = fake.calls[0]
    assert start["method"] == "POST"
    assert start["url"] == "https://auth.x.ai/oauth2/device/code"
    assert start["form"] == {
        "client_id": "b1a00492-073a-47ea-816f-4c329264a828",
        "scope": "openid profile email offline_access grok-cli:access api:access",
        "referrer": "olga-companion",
    }
    h = {k.lower(): v for k, v in start["headers"].items()}
    assert h["content-type"] == "application/x-www-form-urlencoded"
    assert h["accept"] == "application/json"
    assert "olga" in h["user-agent"].lower()
    assert "opencode" not in json.dumps(start).lower() and "grok-build" not in json.dumps(start)
    assert wait_state("pending")["state"] == "pending"
    xai_oauth.logout()


def test_pending_then_success_connects_and_persists(monkeypatch, sleeps):
    fake = install(
        monkeypatch,
        device_handler(
            [
                (400, {"error": "authorization_pending"}),
                (400, {"error": "authorization_pending"}),
                ok_token(),
            ]
        ),
    )
    xai_oauth.start_login()
    st = wait_state("connected")
    assert sleeps[:2] == [5, 5]
    poll = fake.token_calls("device_code")[0]["form"]
    assert poll == {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "client_id": "b1a00492-073a-47ea-816f-4c329264a828",
        "device_code": "DEV-secret",
    }
    stored = json.loads(xai_oauth.TOKENS_FILE.read_text())
    assert stored["access_token"] == "AT-secret" and stored["refresh_token"] == "RT-secret"
    assert stored["expires_at"] == pytest.approx(time.time() + 3600, abs=30)
    assert st["state"] == "connected"


def test_slow_down_adds_five_seconds(monkeypatch, sleeps):
    install(
        monkeypatch,
        device_handler(
            [
                (400, {"error": "slow_down"}),
                (400, {"error": "slow_down"}),
                ok_token(),
            ]
        ),
    )
    xai_oauth.start_login()
    wait_state("connected")
    assert sleeps[:2] == [10, 15]


def test_interval_defaults_to_five_and_floors_at_one(monkeypatch, sleeps):
    def handler(method, url, form, headers):
        if url.endswith("/device/code"):
            body = {k: v for k, v in DEVICE.items() if k != "interval"}
            return 200, body
        return (200, {"access_token": "AT-secret", "refresh_token": "RT-secret"}) if sleeps else (400, {"error": "authorization_pending"})

    install(monkeypatch, handler)
    xai_oauth.start_login()
    wait_state("connected")
    assert sleeps[0] == 5
    assert xai_oauth._poll_interval({"interval": 0}) == 1
    assert xai_oauth._poll_interval({}) == 5


@pytest.mark.parametrize("code", ["access_denied", "authorization_denied"])
def test_denied(monkeypatch, code):
    install(monkeypatch, device_handler([(400, {"error": code, "error_description": "no"})]))
    xai_oauth.start_login()
    st = wait_state("denied")
    assert st["message"] and not xai_oauth.TOKENS_FILE.exists()


def test_expired_token(monkeypatch):
    install(monkeypatch, device_handler([(400, {"error": "expired_token"})]))
    xai_oauth.start_login()
    st = wait_state("expired")
    assert st["message"]


def test_missing_refresh_token_is_error(monkeypatch):
    install(monkeypatch, device_handler([(200, {"access_token": "AT-secret", "expires_in": 3600})]))
    xai_oauth.start_login()
    st = wait_state("error")
    assert st["message"] and not xai_oauth.TOKENS_FILE.exists()


def test_expiry_falls_back_to_jwt_exp_then_3600(monkeypatch):
    exp = int(time.time()) + 7200
    seg = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    jwt = f"h.{seg}.s"
    assert xai_oauth._expires_at({"access_token": jwt}) == exp
    assert xai_oauth._expires_at({"access_token": "opaque"}) == pytest.approx(time.time() + 3600, abs=5)
    assert xai_oauth._expires_at({"access_token": jwt, "expires_in": 100}) == pytest.approx(time.time() + 100, abs=5)


def test_start_failure_raises_korean_error_without_secrets(monkeypatch):
    install(monkeypatch, lambda *a: (500, {"error": "boom"}))
    with pytest.raises(xai_oauth.XaiAuthError) as err:
        xai_oauth.start_login()
    assert any("가" <= ch <= "힣" for ch in str(err.value))


# ---- token store ----------------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_token_file_is_0600_and_atomic(monkeypatch):
    replaced = []
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (replaced.append((a, b)), real_replace(a, b))[1])
    write_tokens(3600)
    assert stat.S_IMODE(xai_oauth.TOKENS_FILE.stat().st_mode) == 0o600
    assert replaced and str(replaced[0][1]) == str(xai_oauth.TOKENS_FILE)

    before = xai_oauth.TOKENS_FILE.read_text()

    def boom(a, b):
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_tokens(10, access="AT-rotated", refresh="RT-rotated")
    assert xai_oauth.TOKENS_FILE.read_text() == before
    assert [p.name for p in xai_oauth.TOKENS_FILE.parent.iterdir() if p.name.endswith(".tmp") or p.name.startswith(".xai")] == []


def test_status_never_contains_tokens_or_device_code(monkeypatch):
    install(monkeypatch, device_handler([(400, {"error": "authorization_pending"})]))
    pending = xai_oauth.start_login()
    wait_state("pending")
    blob = json.dumps(pending) + json.dumps(xai_oauth.login_status())
    install(monkeypatch, device_handler([ok_token()]))
    xai_oauth.logout()
    xai_oauth.start_login()
    wait_state("connected")
    blob += json.dumps(xai_oauth.login_status())
    for secret in SECRETS:
        assert secret not in blob
    assert not {"access_token", "refresh_token", "device_code"} & set(xai_oauth.login_status())


def test_idle_then_connected_from_existing_file_then_logout():
    assert xai_oauth.login_status()["state"] == "idle"
    write_tokens(3600)
    assert xai_oauth.login_status()["state"] == "connected"
    xai_oauth.logout()
    assert not xai_oauth.TOKENS_FILE.exists()
    assert xai_oauth.login_status()["state"] == "idle"


# ---- refresh ---------------------------------------------------------------------------------------

def test_fresh_token_is_returned_without_http(monkeypatch):
    fake = install(monkeypatch, lambda *a: pytest.fail("no http expected"))
    write_tokens(3600)
    assert xai_oauth.get_fresh_access_token() == "AT-secret"
    assert fake.calls == []


def test_refresh_within_five_minutes_rotates_and_persists(monkeypatch):
    fake = install(
        monkeypatch,
        lambda *a: (200, {"access_token": "AT-rotated", "refresh_token": "RT-rotated", "expires_in": 3600}),
    )
    write_tokens(200)
    assert xai_oauth.get_fresh_access_token() == "AT-rotated"
    form = fake.token_calls("refresh_token")[0]["form"]
    assert form == {
        "grant_type": "refresh_token",
        "refresh_token": "RT-secret",
        "client_id": "b1a00492-073a-47ea-816f-4c329264a828",
    }
    stored = json.loads(xai_oauth.TOKENS_FILE.read_text())
    assert stored["refresh_token"] == "RT-rotated" and stored["access_token"] == "AT-rotated"


def test_refresh_keeps_old_refresh_token_when_server_omits_one(monkeypatch):
    install(monkeypatch, lambda *a: (200, {"access_token": "AT-rotated", "expires_in": 3600}))
    write_tokens(10)
    xai_oauth.get_fresh_access_token()
    assert json.loads(xai_oauth.TOKENS_FILE.read_text())["refresh_token"] == "RT-secret"


def test_concurrent_refresh_is_single_flight(monkeypatch):
    def handler(method, url, form, headers):
        time.sleep(0.15)
        return 200, {"access_token": "AT-rotated", "refresh_token": "RT-rotated", "expires_in": 3600}

    fake = install(monkeypatch, handler)
    write_tokens(10)
    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(xai_oauth.get_fresh_access_token())) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert results == ["AT-rotated", "AT-rotated"]
    assert len(fake.token_calls("refresh_token")) == 1


def test_invalid_grant_clears_tokens_and_asks_to_reconnect(monkeypatch):
    install(monkeypatch, lambda *a: (400, {"error": "invalid_grant"}))
    write_tokens(10)
    with pytest.raises(xai_oauth.XaiAuthError):
        xai_oauth.get_fresh_access_token()
    assert xai_oauth.login_status()["state"] == "idle"


def test_not_connected_raises():
    with pytest.raises(xai_oauth.XaiAuthError):
        xai_oauth.get_fresh_access_token()


# ---- inference client ------------------------------------------------------------------------------

def _run_client(monkeypatch, behaviours):
    seen_tokens = []
    queue = list(behaviours)

    async def fake_stream(self, **kwargs):
        seen_tokens.append(self._access_token)
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(OpenAIResponsesApiClient, "stream_generate", fake_stream)
    client = xai_oauth.build_responses_client()
    assert isinstance(client, OpenAIResponsesApiClient)
    assert client._base_url == "https://api.x.ai/v1"
    assert client._extra_headers == {} and not client._reasoning and not client._text
    return client, seen_tokens


def test_401_refreshes_once_then_succeeds(monkeypatch):
    fake = install(
        monkeypatch,
        lambda *a: (200, {"access_token": "AT-rotated", "refresh_token": "RT-rotated", "expires_in": 3600}),
    )
    write_tokens(3600)
    client, seen = _run_client(monkeypatch, [ValueError("Authentication failed (401)"), "OK"])
    out = asyncio.run(client.stream_generate(conversation=None, model="m", system_instruction=""))
    assert out == "OK"
    assert seen == ["AT-secret", "AT-rotated"]
    assert len(fake.token_calls("refresh_token")) == 1


def test_401_twice_fails_after_a_single_refresh(monkeypatch):
    fake = install(
        monkeypatch,
        lambda *a: (200, {"access_token": "AT-rotated", "refresh_token": "RT-rotated", "expires_in": 3600}),
    )
    write_tokens(3600)
    client, seen = _run_client(
        monkeypatch, [ValueError("Authentication failed (401)"), ValueError("Authentication failed (401)")]
    )
    with pytest.raises(ValueError) as err:
        asyncio.run(client.stream_generate(conversation=None, model="m", system_instruction=""))
    assert len(fake.token_calls("refresh_token")) == 1 and len(seen) == 2
    assert not any(s in str(err.value) for s in SECRETS)


def test_403_fails_closed_with_korean_subscription_message(monkeypatch):
    fake = install(monkeypatch, lambda *a: pytest.fail("403 must not refresh"))
    write_tokens(3600)
    client, seen = _run_client(monkeypatch, [ValueError("Forbidden (403): {\"error\":\"RT-secret\"}")])
    with pytest.raises(ValueError) as err:
        asyncio.run(client.stream_generate(conversation=None, model="m", system_instruction=""))
    msg = str(err.value)
    assert "구독" in msg and "다시 연결" in msg and "다른 공급자" in msg
    assert "RT-secret" not in msg and len(seen) == 1 and fake.calls == []


def test_426_reports_client_version_refused(monkeypatch):
    install(monkeypatch, lambda *a: pytest.fail("no http"))
    write_tokens(3600)
    client, _ = _run_client(monkeypatch, [ValueError("Responses API error 426: upgrade")])
    with pytest.raises(ValueError) as err:
        asyncio.run(client.stream_generate(conversation=None, model="m", system_instruction=""))
    assert "버전" in str(err.value)


# ---- models ----------------------------------------------------------------------------------------

def test_models_fetched_live_with_bearer_and_cached(monkeypatch):
    fake = install(
        monkeypatch,
        lambda *a: (
            200,
            {
                "models": [
                    {"id": "live-model-a", "output_modalities": ["text"]},
                    {"id": "live-model-b", "output_modalities": ["text"]},
                    {"nope": 1},
                ]
            },
        ),
    )
    write_tokens(3600)
    models = xai_oauth.list_chat_models()
    assert [m["id"] for m in models] == ["live-model-a", "live-model-b"]
    call = fake.calls[0]
    assert call["method"] == "GET" and call["url"] == "https://api.x.ai/v1/language-models"
    assert {k.lower(): v for k, v in call["headers"].items()}["authorization"] == "Bearer AT-secret"
    xai_oauth.list_chat_models()
    assert len(fake.calls) == 1


def test_language_model_list_keeps_text_output_only(monkeypatch):
    fake = install(
        monkeypatch,
        lambda *a: (
            200,
            {
                "models": [
                    {"id": "grok-text", "input_modalities": ["text"], "output_modalities": ["text"]},
                    {
                        "id": "grok-vision",
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    },
                    {"id": "grok-imagine-image", "output_modalities": ["image"]},
                    {"id": "grok-imagine-video", "output_modalities": ["video"]},
                    {"id": "grok-both", "output_modalities": ["text", "image"]},
                    {"id": "grok-bare"},
                    {"id": ""},
                ]
            },
        ),
    )
    write_tokens(3600)

    assert [m["id"] for m in xai_oauth.list_chat_models()] == ["grok-text", "grok-vision"]
    assert all("/image-generation-models" not in call["url"] for call in fake.calls)
    assert all("/video-generation-models" not in call["url"] for call in fake.calls)


def test_models_empty_when_disconnected(monkeypatch):
    fake = install(monkeypatch, lambda *a: pytest.fail("no http when disconnected"))
    assert xai_oauth.list_chat_models() == []
    assert fake.calls == []


def test_catalog_and_factory_wiring(monkeypatch):
    from olga_companion.llm import catalog, factory

    install(
        monkeypatch,
        lambda *a: (200, {"models": [{"id": "live-model-a", "output_modalities": ["text"]}]}),
    )
    assert catalog.is_known_provider("xai")
    assert catalog.available_models("xai") == []
    write_tokens(3600)
    assert [m["id"] for m in catalog.available_models("xai")] == ["live-model-a"]
    assert catalog.default_model("xai") == "live-model-a"
    assert factory.build_llm_client("xai", "live-model-a", "medium") is not None


def test_chat_builds_responses_client_for_xai(monkeypatch):
    from olga_companion.agent import chat

    install(monkeypatch, lambda *a: pytest.fail("fresh token needs no http"))
    assert chat._build_real_client("xai", "m", "medium") is None
    write_tokens(3600)
    client = chat._build_real_client("xai", "m", "medium")
    assert isinstance(client, OpenAIResponsesApiClient)
    assert client._base_url == "https://api.x.ai/v1" and client._access_token == "AT-secret"
