from __future__ import annotations

from typing import Any

import pytest

from olga_companion.llm import codex_oauth


def _credentials() -> codex_oauth.CodexCredentials:
    return codex_oauth.CodexCredentials(
        access_token="old-access",
        refresh_token="old-refresh",
        id_token="old-id",
        account_id="account",
        source="app_oauth",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": ["not-a-token"]},
        {"access_token": "new-access", "refresh_token": {"nested": "token"}},
        {"access_token": "new-access", "id_token": 42},
    ],
)
def test_refresh_application_rejects_non_string_token_fields(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(codex_oauth.CodexAuthError, match="올바르지"):
        codex_oauth._apply_refresh_response(_credentials(), payload)


def test_refresh_transport_rejects_non_string_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"access_token": ["not-a-token"]}

    class Client:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        @staticmethod
        def post(*_args: Any, **_kwargs: Any) -> Response:
            return Response()

    monkeypatch.setattr(codex_oauth.httpx, "Client", Client)

    with pytest.raises(codex_oauth.CodexAuthError, match="올바르지"):
        codex_oauth._post_token_refresh("secret-refresh")
