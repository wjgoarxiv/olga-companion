"""PKCE authorization URL construction and browser-launch fallbacks."""

from __future__ import annotations

import logging
import urllib.parse
from collections.abc import Callable
from typing import Any


def build_auth_url(
    code_challenge: str,
    *,
    client_id: str,
    redirect_uri: str,
    auth_endpoint: str,
    scopes: str,
    state_factory: Callable[[int], str],
) -> tuple[str, str]:
    """Build a state-bound Codex PKCE authorization URL."""
    state = state_factory(32)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "codex_cli_rs",
    }
    return f"{auth_endpoint}?{urllib.parse.urlencode(params)}", state


def make_strict_callback_handler(
    expected_state: str,
    *,
    handler_factory: Callable[[str], type[Any]],
) -> type[Any]:
    """Reject callback ambiguity before delegating to the HTML handler."""
    base_handler = handler_factory(expected_state)

    class StrictCallbackHandler(base_handler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            states = params.get("state", [])
            codes = params.get("code", [])
            if (
                parsed.path != "/auth/callback"
                or len(states) != 1
                or len(codes) > 1
            ):
                self.send_response(400)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"invalid OAuth callback")
                return
            super().do_GET()

    return StrictCallbackHandler


def open_signin_browser(
    auth_url: str,
    *,
    browser_open: Callable[[str], bool],
    startfile: Callable[[str], None] | None,
    logger: logging.Logger,
) -> bool:
    """Open the sign-in URL using browser discovery then Windows shell-open."""
    try:
        if browser_open(auth_url):
            logger.info("codex self-OAuth: browser opened via webbrowser")
            return True
    except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
        logger.warning(
            "codex self-OAuth: webbrowser.open failed: %s", type(exc).__name__
        )
    if startfile is not None:
        try:
            startfile(auth_url)
            logger.info("codex self-OAuth: browser opened via os.startfile")
            return True
        except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            logger.warning(
                "codex self-OAuth: os.startfile failed: %s", type(exc).__name__
            )
    logger.warning("codex self-OAuth: could NOT open a browser automatically")
    return False
