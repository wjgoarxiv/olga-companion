"""API-key connections: write-only secret, verified chat, no network."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from olga_companion.agent import chat as chat_mod
from olga_companion.agent import history, session_token
from olga_companion.llm import api_key_connections as keys
from olga_companion.llm import catalog, factory
from olga_companion.sidecar import app

CANARY = "CANARY-KEY-olga-21-do-not-leak"
BASE = "https://api.example.com/v1"


def _headers() -> dict[str, str]:
    return {"X-Session-Token": session_token.boot_token()}


def _body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": "Example",
        "protocol": "openai-chat",
        "base_url": BASE,
        "model": "gpt-owner",
        "key": CANARY,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(keys, "metadata_path", lambda: tmp_path / "apikey-connections.json")
    return TestClient(app)


def _assert_canary_absent(text: str) -> None:
    assert CANARY not in text


def test_insecure_scheme_and_bad_urls_are_rejected_without_echoing_the_key(client: TestClient) -> None:
    insecure = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(base_url="http://api.example.com/v1"),
    )
    userinfo = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(base_url=f"https://{CANARY}@api.example.com/v1"),
    )
    query = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(base_url="https://api.example.com/v1?q=1"),
    )
    fragment = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(base_url="https://api.example.com/v1#key"),
    )

    assert insecure.status_code == 400
    assert insecure.json() == {"outcome": "insecure_scheme"}
    assert userinfo.json()["outcome"] == "invalid_base_url"
    assert query.json()["outcome"] == "invalid_base_url"
    assert fragment.json()["outcome"] == "invalid_base_url"
    for response in (insecure, userinfo, query, fragment):
        _assert_canary_absent(response.text)
        _assert_canary_absent(str(response.headers))


def test_anthropic_messages_is_unsupported_until_an_adapter_exists(client: TestClient) -> None:
    response = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(protocol="anthropic-messages"),
    )

    assert response.status_code == 400
    assert response.json() == {"outcome": "unsupported_protocol"}
    _assert_canary_absent(response.text)


@pytest.mark.parametrize(
    ("override", "outcome"),
    [
        ({"model": "  "}, "missing_model"),
        ({"key": ""}, "missing_key"),
        ({"label": ""}, "invalid_label"),
        ({"label": "x" * 41}, "invalid_label"),
    ],
)
def test_missing_or_invalid_fields_fail_closed(
    client: TestClient, override: dict[str, str], outcome: str
) -> None:
    response = client.post("/api/providers/apikey", headers=_headers(), json=_body(**override))

    assert response.status_code == 400
    assert response.json() == {"outcome": outcome}
    _assert_canary_absent(response.text)


def test_save_lists_last4_and_stores_the_key_outside_metadata(
    client: TestClient, tmp_path: Path
) -> None:
    saved = client.post("/api/providers/apikey", headers=_headers(), json=_body())
    listed = client.get("/api/providers/apikey", headers=_headers())

    assert saved.status_code == 200
    body = saved.json()
    assert body["outcome"] == "saved"
    assert CANARY not in saved.text
    connection = listed.json()["connections"][0]
    assert connection["id"] == body["id"]
    assert connection["last4"] == CANARY[-4:]
    assert connection["has_key"] is True
    assert connection["verified"] is False
    assert connection["last_outcome"] is None
    assert "key" not in connection
    metadata = (tmp_path / "apikey-connections.json").read_text(encoding="utf-8")
    _assert_canary_absent(metadata)
    from olga_companion import config

    stored = config.private_state_root() / "apikeys" / body["id"]
    assert stored.read_text(encoding="utf-8") == CANARY
    assert stored.stat().st_mode & 0o777 == 0o600


class _UnreadResponse:
    """Status line only. Reading the body is a failed verify probe."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def close(self) -> None:
        return None

    def _refuse_body(self) -> None:
        raise AssertionError("verify read the response body")

    @property
    def text(self) -> str:
        self._refuse_body()

    @property
    def content(self) -> bytes:
        self._refuse_body()

    def read(self) -> bytes:
        self._refuse_body()

    def json(self) -> object:
        self._refuse_body()

    def iter_bytes(self, chunk_size: int | None = None) -> object:
        self._refuse_body()


def _chat_probe(model: str) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
    }


def _responses_probe(model: str) -> dict[str, object]:
    return {"model": model, "input": "Reply with OK.", "stream": False}


def test_verify_posts_the_chat_probe_and_maps_statuses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url = "http://127.0.0.1:9/v1"
    saved = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(base_url=base_url, model="gpt-owner"),
    ).json()
    responses = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(base_url=base_url, protocol="openai-responses", model="claude-owner"),
    ).json()
    seen: list[dict[str, object]] = []
    created: dict[str, object] = {}
    script: list[object] = [200, 401, 403, 404, 429, 400, 422, 500, "down", "timeout", 302, 200]

    def _next() -> _UnreadResponse:
        step = script.pop(0)
        request = httpx.Request("POST", base_url)
        if step == "down":
            raise httpx.ConnectError("down", request=request)
        if step == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        return _UnreadResponse(int(step))

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def get(self, url: str, headers: dict[str, str] | None = None) -> _UnreadResponse:
            seen.append(
                {
                    "method": "GET",
                    "url": url,
                    "headers": dict(headers or {}),
                    "json": None,
                    "stream": False,
                }
            )
            return _next()

        def post(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            json: dict[str, object] | None = None,
        ) -> _UnreadResponse:
            seen.append(
                {
                    "method": "POST",
                    "url": url,
                    "headers": dict(headers or {}),
                    "json": json,
                    "stream": False,
                }
            )
            return _next()

        def build_request(
            self,
            method: str,
            url: str,
            headers: dict[str, str] | None = None,
            json: dict[str, object] | None = None,
        ) -> httpx.Request:
            seen.append(
                {
                    "method": method,
                    "url": url,
                    "headers": dict(headers or {}),
                    "json": json,
                    "stream": None,
                }
            )
            return httpx.Request(method, url, headers=headers)

        def send(self, request: httpx.Request, stream: bool = False) -> _UnreadResponse:
            if seen:
                seen[-1]["stream"] = stream
            return _next()

    monkeypatch.setattr(httpx, "Client", _Client)
    chat_id = saved["id"]
    logs: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logs.append(record.getMessage())

    handler_log = _Capture()
    logger = logging.getLogger("olga_companion.runtime_diagnostics")
    logger.addHandler(handler_log)
    try:
        results = [
            client.post(f"/api/providers/apikey/{chat_id}/verify", headers=_headers())
            for _ in range(11)
        ]
        results.append(
            client.post(f"/api/providers/apikey/{responses['id']}/verify", headers=_headers())
        )
    finally:
        logger.removeHandler(handler_log)

    chat_call = {
        "method": "POST",
        "url": f"{base_url}/chat/completions",
        "headers": {
            "Authorization": f"Bearer {CANARY}",
            "Content-Type": "application/json",
        },
        "json": _chat_probe("gpt-owner"),
        "stream": True,
    }
    assert created["timeout"] == 20
    assert created["follow_redirects"] is False
    assert created["trust_env"] is False
    assert seen == [chat_call] * 11 + [
        {
            "method": "POST",
            "url": f"{base_url}/responses",
            "headers": {
                "Authorization": f"Bearer {CANARY}",
                "Content-Type": "application/json",
            },
            "json": _responses_probe("claude-owner"),
            "stream": True,
        }
    ]
    assert [item.json() for item in results] == [
        {"outcome": "verified"},
        {"outcome": "unauthorized", "http_status": 401},
        {"outcome": "unauthorized", "http_status": 403},
        {"outcome": "not_found", "http_status": 404},
        {"outcome": "rate_limited", "http_status": 429},
        {"outcome": "request_rejected", "http_status": 400},
        {"outcome": "request_rejected", "http_status": 422},
        {"outcome": "unexpected_response", "http_status": 500},
        {"outcome": "unreachable", "http_status": None},
        {"outcome": "unreachable", "http_status": None},
        {"outcome": "unexpected_response", "http_status": 302},
        {"outcome": "verified"},
    ]
    assert all("evil.example" not in str(item["url"]) for item in seen)
    for response in results:
        _assert_canary_absent(response.text)
        _assert_canary_absent(str(response.headers))
    assert all(CANARY not in line for line in logs)


def test_verify_post_does_not_follow_redirects_or_trust_env(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = client.post(
        "/api/providers/apikey",
        headers=_headers(),
        json=_body(base_url="http://127.0.0.1:9/v1"),
    ).json()
    created: dict[str, object] = {}
    calls: list[tuple[str, str]] = []

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
            calls.append(("GET", url))
            return httpx.Response(
                302,
                headers={"location": "https://evil.example/models"},
                request=httpx.Request("GET", url),
            )

        def build_request(
            self,
            method: str,
            url: str,
            headers: dict[str, str] | None = None,
            json: dict[str, object] | None = None,
        ) -> httpx.Request:
            calls.append((method, url))
            return httpx.Request(method, url, headers=headers)

        def send(self, request: httpx.Request, stream: bool = False) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"location": "https://evil.example/chat"},
                request=request,
            )

    monkeypatch.setattr(httpx, "Client", _Client)
    result = keys.verify_connection(saved["id"])

    assert calls == [("POST", "http://127.0.0.1:9/v1/chat/completions")]
    assert created["follow_redirects"] is False
    assert created["trust_env"] is False
    assert created["timeout"] == 20
    assert result == {"outcome": "unexpected_response", "http_status": 302}


def test_verify_releases_the_lock_during_the_network_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = client.post("/api/providers/apikey", headers=_headers(), json=_body()).json()

    def _lock_is_free() -> None:
        assert keys._LOCK.acquire(blocking=False) is True
        keys._LOCK.release()

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            return None

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
            _lock_is_free()
            return httpx.Response(200, request=httpx.Request("GET", url))

        def build_request(
            self,
            method: str,
            url: str,
            headers: dict[str, str] | None = None,
            json: dict[str, object] | None = None,
        ) -> httpx.Request:
            _lock_is_free()
            return httpx.Request(method, url, headers=headers)

        def send(self, request: httpx.Request, stream: bool = False) -> httpx.Response:
            return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx, "Client", _Client)

    verified = keys.verify_connection(saved["id"])

    assert verified == {"outcome": "verified"}


def test_short_key_last4_is_not_the_whole_secret(client: TestClient) -> None:
    saved = client.post(
        "/api/providers/apikey", headers=_headers(), json=_body(key="abcd")
    )
    listed = client.get("/api/providers/apikey", headers=_headers())

    assert saved.status_code == 200
    connection = listed.json()["connections"][0]
    assert connection["last4"] != "abcd"
    assert "abcd" not in saved.text
    assert "abcd" not in listed.text


def test_failed_catalog_write_removes_the_orphan_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olga_companion import config

    def boom(_connections: list) -> None:
        raise OSError("disk")

    monkeypatch.setattr(keys, "_write", boom)

    with pytest.raises(OSError, match="disk"):
        keys.save_connection(_body())

    stored = config.private_state_root() / "apikeys"
    assert list(stored.glob("*")) == []


def test_delete_removes_the_file_secret(client: TestClient) -> None:
    from olga_companion import config

    saved = client.post("/api/providers/apikey", headers=_headers(), json=_body()).json()
    stored = config.private_state_root() / "apikeys" / saved["id"]
    assert stored.is_file()

    deleted = client.delete(f"/api/providers/apikey/{saved['id']}", headers=_headers())

    assert deleted.json() == {"deleted": True}
    assert not stored.exists()
    assert client.get("/api/providers/apikey", headers=_headers()).json()["connections"] == []
    _assert_canary_absent(deleted.text)


def test_windows_delete_removes_the_credential(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, str] = {}

    def write(target: str, secret: str) -> None:
        assert target.startswith("OLGA Companion/apikey/")
        store[target] = secret

    def read(target: str) -> str:
        return store[target]

    def delete(target: str) -> None:
        store.pop(target)

    monkeypatch.setattr(keys, "_windows_credential_store", lambda: True)
    monkeypatch.setattr(keys, "_cred_write", write)
    monkeypatch.setattr(keys, "_cred_read", read)
    monkeypatch.setattr(keys, "_cred_delete", delete)
    saved = client.post("/api/providers/apikey", headers=_headers(), json=_body()).json()
    from olga_companion import config

    assert not (config.private_state_root() / "apikeys" / saved["id"]).exists()
    assert store[f"OLGA Companion/apikey/{saved['id']}"] == CANARY

    client.delete(f"/api/providers/apikey/{saved['id']}", headers=_headers())

    assert store == {}


def test_chat_sends_the_key_only_in_authorization_and_keeps_it_out_of_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = client.post("/api/providers/apikey", headers=_headers(), json=_body()).json()

    def fake_post(
        url: str, headers: dict[str, str], payload: dict[str, object], timeout: float
    ) -> httpx.Response:
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(keys, "_http_post", fake_post)
    assert client.post(
        f"/api/providers/apikey/{saved['id']}/verify", headers=_headers()
    ).json()["outcome"] == "verified"
    captured: list[dict[str, object]] = []

    class _Response:
        status = 200

        async def text(self) -> str:
            return CANARY

        @property
        def content(self) -> _Response:
            return self

        async def iter_any(self):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    class _Session:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

        def post(self, url: str, json: dict | None = None, headers: dict | None = None) -> _Response:
            captured.append({"url": url, "json": json or {}, "headers": headers or {}})
            return _Response()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", _Session)
    agent = chat_mod.build_client("apikey", saved["id"], "medium")
    conversation = agent.create_conversation(saved["id"])
    conversation.add_user_message("hello from the operator")
    asyncio.run(
        agent.stream_generate(
            conversation=conversation,
            model=saved["id"],
            system_instruction="system",
            tools=None,
        )
    )
    session_id = client.post(
        "/api/chat/session", json={"title": "key"}, headers=_headers()
    ).json()["session_id"]
    logs: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logs.append(record.getMessage())

    handler = _Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        response = client.post(
            "/api/chat",
            headers={**_headers(), "x-llm-provider": "apikey", "x-llm-model": saved["id"]},
            json={"session_id": session_id, "message": "hello from the operator"},
        )
    finally:
        root.removeHandler(handler)

    assert captured, response.text
    sent = captured[0]
    assert sent["headers"]["Authorization"] == f"Bearer {CANARY}"
    encoded = json.dumps(sent["json"])
    _assert_canary_absent(encoded)
    assert "gpt-owner" in encoded
    assert sent["url"] == "https://api.example.com/v1/chat/completions"
    _assert_canary_absent(response.text)
    _assert_canary_absent(str(response.headers))
    history_text = (history.chats_root() / f"{session_id}.jsonl").read_text(encoding="utf-8")
    _assert_canary_absent(history_text)
    assert all(CANARY not in line for line in logs)
    names = [item["provider"] for item in client.get("/api/providers").json()["providers"]]
    assert "apikey" in names
    listed = next(
        item for item in client.get("/api/providers").json()["providers"] if item["provider"] == "apikey"
    )
    assert listed["models"] == [{"id": saved["id"], "label": "Example"}]
    assert catalog.is_valid_model("apikey", saved["id"]) is True
    assert factory.build_llm_client("apikey", saved["id"], "medium") is not None


def test_malformed_port_and_hostname_are_rejected(client: TestClient) -> None:
    for base_url in (
        "https://host:abc/v1",
        "https://api.example.com:99999/v1",
        "https://api.example.com:0/v1",
        "https://exa mple.com/v1",
    ):
        response = client.post(
            "/api/providers/apikey", headers=_headers(), json=_body(base_url=base_url)
        )

        assert response.json() == {"outcome": "invalid_base_url"}, base_url
        _assert_canary_absent(response.text)


def test_verify_catches_invalid_url_as_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = client.post(
        "/api/providers/apikey", headers=_headers(), json=_body()
    ).json()

    def _boom(url: str, headers: dict, payload: dict, timeout: float) -> httpx.Response:
        raise httpx.InvalidURL("malformed host")

    monkeypatch.setattr(keys, "_http_post", _boom)
    result = keys.verify_connection(saved["id"])

    assert result == {"outcome": "unreachable", "http_status": None}


def _reverify_with_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, status: int | None
) -> dict:
    saved = client.post(
        "/api/providers/apikey", headers=_headers(), json=_body()
    ).json()
    monkeypatch.setattr(keys, "_http_post", lambda *a, **k: httpx.Response(200))
    assert keys.verify_connection(saved["id"]) == {"outcome": "verified"}
    first = next(
        item for item in keys.list_connections() if item["id"] == saved["id"]
    )
    assert first["verified"] is True

    if status is None:
        monkeypatch.setattr(
            keys, "_http_post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down"))
        )
    else:
        monkeypatch.setattr(
            keys,
            "_http_post",
            lambda *a, **k: httpx.Response(status),
        )
    result = keys.verify_connection(saved["id"])
    listed = next(
        item for item in keys.list_connections() if item["id"] == saved["id"]
    )
    return {"result": result, "verified": listed["verified"], "last": listed["last_outcome"]}


def test_reverify_transient_failure_keeps_verified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for status in (429, 500, None):
        outcome = _reverify_with_status(client, monkeypatch, status)

        assert outcome["verified"] is True
        assert outcome["result"]["outcome"] in ("rate_limited", "unexpected_response", "unreachable")
        assert keys.catalog_entries() != []


def test_reverify_auth_failure_demotes_to_unverified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for status, outcome in ((401, "unauthorized"), (403, "unauthorized"), (404, "not_found"), (400, "request_rejected")):
        checked = _reverify_with_status(client, monkeypatch, status)

        assert checked["verified"] is False
        assert checked["result"] == {"outcome": outcome, "http_status": status}
        assert checked["last"] == outcome
        assert keys.catalog_entries() == []


def test_unverified_connection_is_not_selectable(client: TestClient) -> None:
    saved = client.post("/api/providers/apikey", headers=_headers(), json=_body()).json()

    assert catalog.is_valid_model("apikey", saved["id"]) is False
    assert factory.build_llm_client("apikey", saved["id"], "medium") is None
    provider, model, _variant = factory.resolve_llm_selection(
        {"x-llm-provider": "apikey", "x-llm-model": saved["id"]}, {}
    )
    assert provider == "apikey"
    assert model == ""
