"""
OpenAI OAuth Authentication for OLGA Companion.

PKCE OAuth flow for OpenAI API access (public client, no client_secret).

Usage:
    python src/openai_auth.py
"""

import os
import json
import logging
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import urllib.request
import urllib.parse
import secrets
import hashlib
import base64
import urllib.error


def _urlopen_safe(req, timeout=30):
    """Network-resilient urlopen for frozen builds.

    Fixes getaddrinfo failures caused by broken system proxy/WPAD in PyInstaller.
    Falls back to httpx if urllib fails entirely.
    Handles enterprise SSL interception (corporate proxy MITM certificates).
    """
    import os
    import ssl

    def _ssl_contexts():
        """Build ordered list of SSL contexts: custom CA → certifi → no-verify."""
        ctxs = []
        # 1. Custom CA bundle from .env (enterprise environments)
        custom_ca = os.environ.get("CUSTOM_CA_BUNDLE", "")
        if custom_ca and os.path.isfile(custom_ca):
            try:
                ctxs.append(ssl.create_default_context(cafile=custom_ca))
            except Exception as e:
                logger.warning(f"CUSTOM_CA_BUNDLE ({custom_ca}) failed: {e}")
        # 2. certifi bundle (standard public CAs)
        try:
            import certifi
            ctxs.append(ssl.create_default_context(cafile=certifi.where()))
        except ImportError:
            pass
        # 3. No-verify fallback (enterprise proxy SSL interception)
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctxs.append(ctx)
        except Exception:
            pass
        return ctxs or [ssl.create_default_context()]

    for ctx in _ssl_contexts():
        insecure = ctx.verify_mode == ssl.CERT_NONE
        # Attempt 1: no-proxy opener (bypasses WPAD/broken system proxy)
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ctx),
            )
            with opener.open(req, timeout=timeout) as resp:
                if insecure:
                    logger.warning("SSL verify disabled — enterprise proxy detected")
                return resp.read().decode()
        except Exception:
            pass

        # Attempt 2: default opener with SSL context
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if insecure:
                    logger.warning("SSL verify disabled — enterprise proxy detected")
                return resp.read().decode()
        except Exception:
            pass

    # Attempt 3: httpx with same SSL fallback strategy
    for verify in [True, False]:
        try:
            import httpx  # noqa: F401 — kept so test monkeypatches of httpx still bind here
            from olga_companion import net
            headers = dict(req.headers)
            with net.sync_client(verify=verify, timeout=timeout) as client:
                if req.data:
                    r = client.post(req.full_url, content=req.data, headers=headers)
                else:
                    r = client.get(req.full_url, headers=headers)
                r.raise_for_status()
                if not verify:
                    logger.warning("httpx SSL verify disabled — enterprise proxy detected")
                return r.text
        except Exception:
            continue

    raise urllib.error.URLError(
        "네트워크 연결 실패 — 인터넷, 방화벽, VPN 설정을 확인하세요.\n"
        "기업 네트워크인 경우 .env에 CUSTOM_CA_BUNDLE=경로를 설정하세요."
    )


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# OpenAI OAuth Constants
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # OpenAI Codex public client
AUTH_ENDPOINT = "https://auth.openai.com/oauth/authorize"
TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
REDIRECT_PORT = 1455  # Must match registered redirect_uri for this client_id
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/auth/callback"
# No client_secret needed for public PKCE clients

# Token storage location
OPENAI_TOKENS_FILE = Path.home() / ".olga_copilot" / "openai_tokens.json"


class OpenAIOAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OpenAI OAuth callback."""

    authorization_code = None
    expected_state = None  # CSRF state token set by build_auth_url()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        """Handle OAuth callback on /auth/callback path."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Validate CSRF state parameter using a constant-time comparison
        # (avoids leaking the expected state via response timing).
        received_state = params.get("state", [None])[0]
        # Read/write on self.__class__, NOT the hardcoded base class: make_oauth_callback_handler
        # creates a per-flow SUBCLASS that shadows expected_state/authorization_code. Hardcoding the
        # base meant do_GET wrote the code to the base while callers read the subclass's None shadow
        # — so every scoped login (run_self_oauth_login) read None and aborted as "취소/시간초과",
        # the exchange never ran, and no token was ever persisted.
        expected_state = self.__class__.expected_state
        if expected_state and not (
            received_state
            and secrets.compare_digest(str(received_state), str(expected_state))
        ):
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            response = """
            <html>
            <head><title>OpenAI Authentication Failed</title></head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                         display: flex; justify-content: center; align-items: center;
                         height: 100vh; margin: 0; background: #fef2f2;">
                <div style="text-align: center; padding: 40px; background: white; border-radius: 16px;
                            box-shadow: 0 10px 40px rgba(0,0,0,0.1);">
                    <h1 style="color: #ef4444; margin: 0 0 16px 0;">&#10008; Authentication Failed</h1>
                    <p style="color: #64748b; margin: 0;">Error: invalid_state — CSRF validation failed.</p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(response.encode())
            return

        # Accept both /auth/callback and root path for compatibility
        if "code" in params:
            self.__class__.authorization_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            response = """
            <html>
            <head><title>OpenAI Authentication Successful</title></head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                         display: flex; justify-content: center; align-items: center;
                         height: 100vh; margin: 0; background: linear-gradient(135deg, #10a37f 0%, #1a7f5a 100%);">
                <div style="text-align: center; padding: 40px; background: white; border-radius: 16px;
                            box-shadow: 0 10px 40px rgba(0,0,0,0.2);">
                    <h1 style="color: #10a37f; margin: 0 0 16px 0;">&#10004; OpenAI Authentication Successful!</h1>
                    <p style="color: #64748b; margin: 0;">You can close this window and return to the application.</p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(response.encode())
        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            response = f"""
            <html>
            <head><title>OpenAI Authentication Failed</title></head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                         display: flex; justify-content: center; align-items: center;
                         height: 100vh; margin: 0; background: #fef2f2;">
                <div style="text-align: center; padding: 40px; background: white; border-radius: 16px;
                            box-shadow: 0 10px 40px rgba(0,0,0,0.1);">
                    <h1 style="color: #ef4444; margin: 0 0 16px 0;">&#10008; OpenAI Authentication Failed</h1>
                    <p style="color: #64748b; margin: 0;">Error: {error}</p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(response.encode())
        else:
            self.send_response(404)
            self.end_headers()


def make_oauth_callback_handler(expected_state: str):
    """Build a per-flow OAuth callback handler class bound to `expected_state`.

    `OpenAIOAuthCallbackHandler` keeps `expected_state` / `authorization_code`
    as class-level attributes, which a concurrent OAuth flow would clobber.
    This factory returns a fresh subclass whose `expected_state` is scoped to
    this flow only; the caller reads `authorization_code` back from the
    returned class. The legacy class-attribute path is left untouched.
    """

    class _ScopedOAuthCallbackHandler(OpenAIOAuthCallbackHandler):
        pass

    _ScopedOAuthCallbackHandler.expected_state = expected_state
    _ScopedOAuthCallbackHandler.authorization_code = None
    return _ScopedOAuthCallbackHandler


def generate_pkce_pair():
    """Generate PKCE code verifier and challenge."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")
    return code_verifier, code_challenge


def build_auth_url(code_challenge: str) -> tuple[str, str]:
    """Build OpenAI OAuth authorization URL with CSRF state.

    Returns:
        Tuple of (auth_url, state_token).
    """
    state = secrets.token_urlsafe(32)
    OpenAIOAuthCallbackHandler.expected_state = state
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid profile email offline_access",
        "audience": "https://api.openai.com/v1",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}", state


def exchange_code_for_tokens(auth_code: str, code_verifier: str) -> dict:
    """Exchange authorization code for tokens (no client_secret for public PKCE)."""
    data = {
        "client_id": CLIENT_ID,
        "code": auth_code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    return json.loads(_urlopen_safe(req))


def refresh_openai_token(refresh_token: str) -> dict:
    """Refresh the OpenAI access token using the refresh token."""
    data = {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    return json.loads(_urlopen_safe(req))


def save_tokens(tokens: dict):
    """Save OpenAI tokens to file."""
    expires_in = tokens.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    token_data = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": expires_at.isoformat(),
        "provider": "openai",
    }

    OPENAI_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    OPENAI_TOKENS_FILE.write_text(json.dumps(token_data, indent=2))
    try:
        os.chmod(OPENAI_TOKENS_FILE, 0o600)
    except OSError:
        pass  # DrvFS may not honour chmod; CI/Linux target is 0600.
    logger.info(f"OpenAI tokens saved to: {OPENAI_TOKENS_FILE}")


def load_tokens() -> dict | None:
    """Load OpenAI tokens from file, auto-refreshing if near expiry.

    Operator UX requirement: once the user signs in, they stay signed in
    across app reloads. OpenAI's short-lived access tokens (≈1h) would
    otherwise disconnect them on every restart. When the token is past
    its `expires_at` (or within the 5 min refresh window) and we still
    have a refresh_token, swap it transparently here.
    Returns None only when (a) no token file, (b) token has no refresh
    handle, or (c) refresh request itself failed.
    """
    try:
        if not OPENAI_TOKENS_FILE.exists():
            return None
        with open(OPENAI_TOKENS_FILE, "r") as f:
            tokens = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load OpenAI tokens: {e}")
        return None

    if not isinstance(tokens, dict):
        return None

    # Refresh window: 5 min before expiry → treat as expired so we never
    # hand back a token that races against an in-flight LLM call.
    expires_at = tokens.get("expires_at")
    refresh_handle = tokens.get("refresh_token") or ""
    if isinstance(expires_at, str) and refresh_handle:
        try:
            parsed = datetime.fromisoformat(expires_at)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if parsed - now < timedelta(minutes=5):
                try:
                    fresh = refresh_openai_token(refresh_handle)
                    # Re-attach any refresh_token the IdP didn't rotate.
                    if not fresh.get("refresh_token"):
                        fresh["refresh_token"] = refresh_handle
                    save_tokens(fresh)
                    with open(OPENAI_TOKENS_FILE, "r") as f:
                        return json.load(f)
                except Exception as e:
                    logger.warning(f"OpenAI token refresh failed: {e}")
                    # Fall through and return the stale token; the caller's
                    # expires_at check will mark them logged out, but at
                    # least we don't crash.
        except Exception:
            pass

    return tokens


def main():
    """Run the OpenAI OAuth authentication flow."""
    print("\n" + "=" * 60)
    print("  OLGA Companion - OpenAI Authentication")
    print("=" * 60 + "\n")

    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()

    # Build auth URL (with CSRF state)
    auth_url, _state = build_auth_url(code_challenge)

    print("Opening browser for OpenAI sign-in...")
    print(f"\nIf browser doesn't open, visit this URL manually:\n{auth_url}\n")

    # Open browser
    webbrowser.open(auth_url)

    # Start local server to receive callback
    server = HTTPServer(("localhost", REDIRECT_PORT), OpenAIOAuthCallbackHandler)
    server.timeout = 300  # 5 minute timeout

    print(f"Waiting for authentication callback on port {REDIRECT_PORT}...")

    # Handle single request
    server.handle_request()

    if OpenAIOAuthCallbackHandler.authorization_code:
        auth_code = OpenAIOAuthCallbackHandler.authorization_code
        print("\nAuthorization code received! Exchanging for tokens...")

        try:
            tokens = exchange_code_for_tokens(auth_code, code_verifier)
            save_tokens(tokens)

            print("\n" + "=" * 60)
            print("  SUCCESS! OpenAI Authentication complete.")
            print("=" * 60)
            print(f"\nTokens saved to: {OPENAI_TOKENS_FILE}")
            print()

        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            print(f"\nERROR: Failed to exchange tokens: {e}")
            return 1
    else:
        print("\nERROR: No authorization code received. Authentication cancelled or failed.")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
