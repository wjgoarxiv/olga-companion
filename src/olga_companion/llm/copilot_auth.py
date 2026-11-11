"""
GitHub Copilot Device Flow Authentication for OlgaCopilot.

Uses GitHub's device code flow to authenticate, then exchanges the GitHub
token for a short-lived Copilot API token.

Usage:
    python src/copilot_auth.py
"""

import os
import json
import logging
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.parse
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
        custom_ca = os.environ.get("CUSTOM_CA_BUNDLE", "")
        if custom_ca and os.path.isfile(custom_ca):
            try:
                ctxs.append(ssl.create_default_context(cafile=custom_ca))
            except Exception as e:
                logger.warning(f"CUSTOM_CA_BUNDLE ({custom_ca}) failed: {e}")
        try:
            import certifi
            ctxs.append(ssl.create_default_context(cafile=certifi.where()))
        except ImportError:
            pass
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
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if insecure:
                    logger.warning("SSL verify disabled — enterprise proxy detected")
                return resp.read().decode()
        except Exception:
            pass

    for verify in [True, False]:
        try:
            import httpx
            headers = dict(req.headers)
            with httpx.Client(verify=verify, timeout=timeout) as client:
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


def _get_opener():
    """Get a no-proxy HTTPS opener for frozen mode resilience."""
    import os
    import ssl
    # Try certifi first, then no-verify for enterprise proxies
    for cafile in [
        os.environ.get("CUSTOM_CA_BUNDLE", ""),
        __import__("certifi").where() if __import__("importlib").util.find_spec("certifi") else "",
    ]:
        if cafile and __import__("os").path.isfile(cafile):
            try:
                ctx = ssl.create_default_context(cafile=cafile)
                return urllib.request.build_opener(
                    urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=ctx),
                )
            except Exception:
                continue
    # Fallback: no-verify for enterprise proxy SSL interception
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    logger.warning("SSL verify disabled — enterprise proxy detected (_get_opener fallback)")
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ctx),
    )


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# GitHub Copilot OAuth Constants
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"  # VS Code Copilot client
DEVICE_CODE_ENDPOINT = "https://github.com/login/device/code"
TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_ENDPOINT = "https://api.github.com/copilot_internal/v2/token"

# Token storage location
COPILOT_TOKENS_FILE = Path.home() / ".olga_copilot" / "copilot_tokens.json"

# Bug 1 — device user_code visibility. The device flow prints the code to the sidecar console only;
# this status file surfaces it (NON-secret: just the user_code + the public github.com/login/device
# URL) so the app UI can show it. Written when the code is obtained, cleared on completion/failure.
LOGIN_STATUS_FILE = Path.home() / ".olga_copilot" / "copilot_login_status.json"


def _write_login_status(user_code: str, verification_uri: str) -> None:
    """Surface the pending device code for the UI. Best-effort; never raises."""
    try:
        LOGIN_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOGIN_STATUS_FILE.write_text(json.dumps({
            "state": "pending",
            "user_code": user_code,
            "verification_uri": verification_uri,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _clear_login_status() -> None:
    """Drop the pending-code marker once the flow finishes (so a dead code never lingers)."""
    try:
        if LOGIN_STATUS_FILE.exists():
            LOGIN_STATUS_FILE.unlink()
    except Exception:  # noqa: BLE001
        pass


def logout() -> None:
    """Disconnect the Copilot provider: delete the stored tokens + any pending
    login-status marker. No-op when absent; never raises."""
    for path in (COPILOT_TOKENS_FILE, LOGIN_STATUS_FILE):
        try:
            if path.is_file():
                path.unlink()
        except Exception:  # noqa: BLE001
            pass


def read_login_status() -> dict | None:
    """Read the pending device-code marker (NON-secret) for the UI. None if absent/invalid."""
    try:
        if LOGIN_STATUS_FILE.exists():
            return json.loads(LOGIN_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None

# Common headers for GitHub API (MUST use Accept: application/json)
_GITHUB_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Headers required by GitHub's Copilot internal token endpoint
_COPILOT_HEADERS = {
    "Authorization": "",  # Set per-request
    "Accept": "application/json",
    "Editor-Version": "vscode/1.95.0",
    "Editor-Plugin-Version": "copilot/1.250.0",
    "User-Agent": "GithubCopilot/1.250.0",
}


def _request_device_code() -> dict:
    """
    Request a device code from GitHub.

    Returns dict with: device_code, user_code, verification_uri, interval, expires_in
    """
    data = urllib.parse.urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "scope": "read:user",
    }).encode()

    req = urllib.request.Request(
        DEVICE_CODE_ENDPOINT,
        data=data,
        headers=_GITHUB_HEADERS,
    )

    return json.loads(_urlopen_safe(req))


def _poll_for_token(device_code: str, interval: int, timeout: int = 300) -> dict:
    """
    Poll GitHub for the access token after user authorizes the device.

    Args:
        device_code: Device code from the initial request
        interval: Polling interval in seconds
        timeout: Maximum time to wait in seconds

    Returns:
        Token response dict with access_token

    Raises:
        TimeoutError: If user doesn't authorize within timeout
        ValueError: If authorization is denied or expired
    """
    data = urllib.parse.urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }).encode()

    start = time.time()

    while time.time() - start < timeout:
        time.sleep(interval)

        req = urllib.request.Request(
            TOKEN_ENDPOINT,
            data=data,
            headers=_GITHUB_HEADERS,
        )

        try:
            with _get_opener().open(req) as response:
                result = json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                result = json.loads(body)
            except Exception:
                raise ValueError(f"GitHub token endpoint error: {e.code} {body}")

        error = result.get("error")

        if error == "authorization_pending":
            # User hasn't authorized yet, keep polling
            continue
        elif error == "slow_down":
            # GitHub wants us to slow down
            interval += 5
            continue
        elif error == "expired_token":
            raise ValueError("Device code expired. Please restart the authentication flow.")
        elif error == "access_denied":
            raise ValueError("Authorization denied by user.")
        elif error:
            raise ValueError(f"GitHub OAuth error: {error} - {result.get('error_description', '')}")
        elif "access_token" in result:
            return result

    raise TimeoutError(f"User did not authorize within {timeout} seconds.")


def _get_copilot_token(github_token: str) -> dict:
    """
    Exchange a GitHub access token for a short-lived Copilot API token.

    Args:
        github_token: GitHub OAuth access token

    Returns:
        dict with: token (short-lived), expires_at (Unix timestamp)
    """
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/json",
        "Editor-Version": _COPILOT_HEADERS["Editor-Version"],
        "Editor-Plugin-Version": _COPILOT_HEADERS["Editor-Plugin-Version"],
        "User-Agent": _COPILOT_HEADERS["User-Agent"],
    }
    req = urllib.request.Request(COPILOT_TOKEN_ENDPOINT, headers=headers)

    try:
        with _get_opener().open(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 403:
            raise ValueError(
                "HTTP Error 403: Forbidden\n"
                "GitHub Copilot 구독이 활성화되어 있는지 확인해주세요."
            )
        raise ValueError(f"Copilot token error ({e.code}): {body}")


def refresh_copilot_token(github_token: str) -> dict:
    """
    Refresh the short-lived Copilot API token using the long-lived GitHub token.

    Args:
        github_token: Long-lived GitHub OAuth access token

    Returns:
        dict with: token, expires_at
    """
    return _get_copilot_token(github_token)


def save_tokens(github_token: str, copilot_data: dict):
    """
    Save both GitHub and Copilot tokens to file.

    Args:
        github_token: Long-lived GitHub OAuth access token
        copilot_data: Copilot token response with 'token' and 'expires_at'
    """
    token_data = {
        "github_token": github_token,
        "copilot_token": copilot_data.get("token", ""),
        "copilot_expires_at": copilot_data.get("expires_at", 0),
        "provider": "copilot",
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    COPILOT_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    COPILOT_TOKENS_FILE.write_text(json.dumps(token_data, indent=2))
    try:
        os.chmod(COPILOT_TOKENS_FILE, 0o600)
    except OSError:
        pass  # DrvFS may not honour chmod; CI/Linux target is 0600.
    logger.info(f"Copilot tokens saved to: {COPILOT_TOKENS_FILE}")


def load_tokens() -> dict | None:
    """Load Copilot tokens from file. Returns None if not found or invalid."""
    try:
        if COPILOT_TOKENS_FILE.exists():
            with open(COPILOT_TOKENS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load Copilot tokens: {e}")
    return None


def get_valid_copilot_token() -> str | None:
    """
    Get a valid Copilot API token, refreshing if expired.

    Returns the short-lived Copilot token string, or None if not authenticated.
    """
    tokens = load_tokens()
    if not tokens or not tokens.get("github_token"):
        return None

    copilot_token = tokens.get("copilot_token", "")
    expires_at = tokens.get("copilot_expires_at", 0)

    # Check if copilot token is expired (with 60s buffer)
    now = time.time()
    if copilot_token and expires_at > now + 60:
        return copilot_token

    # Refresh the short-lived token
    try:
        copilot_data = refresh_copilot_token(tokens["github_token"])
        save_tokens(tokens["github_token"], copilot_data)
        return copilot_data.get("token", "")
    except Exception as e:
        logger.error(f"Failed to refresh Copilot token: {e}")
        return None


# GitHub Copilot's OpenAI-compatible model catalog endpoint. The hardcoded
# antigravity/constants COPILOT_MODELS list went stale (it offered model IDs the
# live chat API rejects with 400 model_not_supported), so the companion reads the
# real per-account list here instead. Cached to avoid a network round-trip on
# every /account/providers + LLM request.
COPILOT_MODELS_ENDPOINT = "https://api.individual.githubcopilot.com/models"
_MODELS_CACHE: dict = {"at": 0.0, "models": None, "refreshing": False}


def _fetch_chat_models() -> list[dict] | None:
    """Network read of the live chat-capable Copilot model list. Returns the parsed
    list, or None on any error (caller keeps the stale cache). Never raises."""
    token = get_valid_copilot_token()
    if not token:
        return None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Editor-Version": _COPILOT_HEADERS["Editor-Version"],
        "Editor-Plugin-Version": _COPILOT_HEADERS["Editor-Plugin-Version"],
        "User-Agent": _COPILOT_HEADERS["User-Agent"],
    }
    req = urllib.request.Request(COPILOT_MODELS_ENDPOINT, headers=headers)
    try:
        data = json.loads(_urlopen_safe(req, timeout=15))
        items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        out: list[dict] = []
        seen: set = set()
        for m in items:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            caps = m.get("capabilities") or {}
            if not mid or caps.get("type") != "chat" or mid in seen:
                continue
            seen.add(mid)
            out.append({
                "id": mid,
                "label": str(m.get("name") or caps.get("family") or mid),
                "picker": bool(m.get("model_picker_enabled")),
            })
        _MODELS_CACHE["models"] = out
        _MODELS_CACHE["at"] = time.time()
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot /models fetch failed: %s", exc)
        return None


def _warm_models_cache() -> None:
    try:
        _fetch_chat_models()
    finally:
        _MODELS_CACHE["refreshing"] = False


def list_chat_models(*, ttl: float = 600.0, cache_only: bool = False) -> list[dict]:
    """Live list of chat-capable Copilot models for the authenticated account.

    Returns [{"id", "label", "picker"}], cached for `ttl` seconds. Returns []
    when Copilot isn't authenticated or on any error (never raises).

    `cache_only=True` NEVER blocks: it returns the cached value (even stale, or [])
    immediately and refreshes in the background. Use it on hot paths like the
    /account/providers status poll, where a synchronous 15s /models fetch on a cache
    miss would stall the route."""
    now = time.time()
    cached = _MODELS_CACHE.get("models")
    fresh = cached is not None and (now - float(_MODELS_CACHE.get("at", 0.0))) < ttl
    if fresh:
        return cached
    if cache_only:
        # Don't block the caller — kick off a single background refresh and serve stale/empty now.
        if not _MODELS_CACHE.get("refreshing"):
            _MODELS_CACHE["refreshing"] = True
            threading.Thread(target=_warm_models_cache, daemon=True).start()
        return cached or []
    out = _fetch_chat_models()
    return out if out is not None else (cached or [])


def main():
    """Run the GitHub Copilot device flow authentication."""
    print("\n" + "=" * 60)
    print("  OlgaCopilot - GitHub Copilot Authentication")
    print("=" * 60 + "\n")

    # Step 1: Request device code
    print("Requesting device code from GitHub...")
    try:
        device_info = _request_device_code()
    except Exception as e:
        print(f"\nERROR: Failed to request device code: {e}")
        return 1

    user_code = device_info["user_code"]
    verification_uri = device_info["verification_uri"]
    interval = device_info.get("interval", 5)

    print(f"\n{'=' * 40}")
    print(f"  Your code: {user_code}")
    print(f"{'=' * 40}")
    print(f"\nOpening {verification_uri} in your browser...")
    print("Enter the code above to authorize.\n")

    # Bug 1 — surface the code for the app UI (it would otherwise be console-only).
    _write_login_status(user_code, verification_uri)
    webbrowser.open(verification_uri)

    # Step 2: Poll for token
    print("Waiting for authorization...")
    try:
        token_result = _poll_for_token(
            device_info["device_code"],
            interval,
            timeout=300,
        )
    except (TimeoutError, ValueError) as e:
        print(f"\nERROR: {e}")
        _clear_login_status()
        return 1

    github_token = token_result["access_token"]
    print("\nGitHub authorization successful!")

    # Step 3: Exchange for Copilot token
    print("Exchanging for Copilot API token...")
    try:
        copilot_data = _get_copilot_token(github_token)
    except Exception as e:
        print(f"\nERROR: Failed to get Copilot token: {e}")
        print("Note: You may not have an active GitHub Copilot subscription.")
        _clear_login_status()
        return 1

    # Step 4: Save tokens
    save_tokens(github_token, copilot_data)
    _clear_login_status()

    print("\n" + "=" * 60)
    print("  SUCCESS! GitHub Copilot Authentication complete.")
    print("=" * 60)
    print(f"\nTokens saved to: {COPILOT_TOKENS_FILE}")
    print()

    return 0


if __name__ == "__main__":
    exit(main())
