"""Token management for Antigravity OAuth."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from .constants import (
    CLIENT_ID,
    CLIENT_SECRET,
    TOKEN_ENDPOINT,
    DEFAULT_PROJECT_ID,
    require_antigravity_oauth_credentials,
)

logger = logging.getLogger(__name__)

# Token storage file location
TOKENS_FILE = Path.home() / ".olga_copilot" / "tokens.json"


@dataclass
class OAuthTokens:
    """OAuth tokens and metadata."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    email: Optional[str] = None
    name: Optional[str] = None
    picture: Optional[str] = None
    project_id: str = DEFAULT_PROJECT_ID
    managed_project_id: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 60s buffer)."""
        return is_token_expired(self.expires_at)

    def to_dict(self) -> dict:
        """Serialize tokens to dict for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
            "project_id": self.project_id,
            "managed_project_id": self.managed_project_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OAuthTokens":
        """Deserialize tokens from dict."""
        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at,
            email=data.get("email"),
            name=data.get("name"),
            picture=data.get("picture"),
            project_id=data.get("project_id", DEFAULT_PROJECT_ID),
            managed_project_id=data.get("managed_project_id"),
        )


def parse_compound_token(compound: str) -> tuple[str, str, Optional[str]]:
    """
    Parse Antigravity compound token format.

    Format: "refresh_token|projectId|managedProjectId"
    or just "refresh_token" for simple tokens.

    Returns:
        Tuple of (refresh_token, project_id, managed_project_id)
    """
    parts = compound.split("|")

    if len(parts) == 1:
        # Simple refresh token
        return parts[0], DEFAULT_PROJECT_ID, None
    elif len(parts) == 2:
        # refresh_token|projectId
        return parts[0], parts[1], None
    elif len(parts) >= 3:
        # refresh_token|projectId|managedProjectId
        return parts[0], parts[1], parts[2]
    else:
        raise ValueError(f"Invalid compound token format: expected 1-3 parts, got {len(parts)}")


def is_token_expired(expires_at: datetime, buffer_seconds: int = 60) -> bool:
    """
    Check if token is expired or will expire soon.

    Args:
        expires_at: Token expiration datetime (should be timezone-aware)
        buffer_seconds: Buffer before actual expiry (default 60s)

    Returns:
        True if token is expired or will expire within buffer
    """
    if expires_at is None:
        return True

    # Ensure we're comparing timezone-aware datetimes
    now = datetime.now(timezone.utc)

    # Make expires_at timezone-aware if it isn't
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    from datetime import timedelta
    return now >= (expires_at - timedelta(seconds=buffer_seconds))


async def refresh_access_token(refresh_token_compound: str) -> OAuthTokens:
    """
    Refresh access token using refresh token.

    Args:
        refresh_token_compound: Compound token in format "refresh_token|projectId|managedProjectId"

    Returns:
        OAuthTokens with fresh access token

    Raises:
        httpx.HTTPStatusError: On HTTP errors
        ValueError: On invalid_grant (token revoked)
    """
    require_antigravity_oauth_credentials()
    refresh_token, project_id, managed_project_id = parse_compound_token(refresh_token_compound)

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    logger.debug(f"Refreshing access token for project: {project_id}")

    _TOKEN_REFRESH_MAX_RETRIES = 3
    _TOKEN_REFRESH_BASE_WAIT = 2  # seconds
    _TRANSPORT_ERRORS = (
        httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
        httpx.WriteTimeout, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout,
    )

    for attempt in range(1, _TOKEN_REFRESH_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    TOKEN_ENDPOINT,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )
            break  # Success — exit retry loop
        except _TRANSPORT_ERRORS as e:
            if attempt < _TOKEN_REFRESH_MAX_RETRIES:
                wait = _TOKEN_REFRESH_BASE_WAIT * (2 ** (attempt - 1))
                logger.warning(f"Token refresh transport error (attempt {attempt}/{_TOKEN_REFRESH_MAX_RETRIES}): {e}. Retrying in {wait}s...")
                import asyncio
                await asyncio.sleep(wait)
            else:
                logger.error(f"Token refresh failed after {_TOKEN_REFRESH_MAX_RETRIES} attempts: {e}")
                raise

    if response.status_code != 200:
        error_data = response.json() if response.content else {}
        error_code = error_data.get("error", "unknown")
        error_desc = error_data.get("error_description", "Unknown error")

        if error_code == "invalid_grant":
            logger.error("Token revoked or expired. User needs to re-authenticate.")
            raise ValueError(f"Token revoked: {error_desc}")

        logger.error(f"Token refresh failed: {error_code} - {error_desc}")
        response.raise_for_status()

    data = response.json()

    # Calculate expiration
    expires_in = data.get("expires_in", 3600)
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    logger.info(f"Token refreshed successfully. Expires at: {expires_at.isoformat()}")

    return OAuthTokens(
        access_token=data["access_token"],
        refresh_token=refresh_token,  # Original refresh token
        expires_at=expires_at,
        project_id=project_id,
        managed_project_id=managed_project_id,
    )


class TokenManager:
    """
    Manages OAuth tokens with automatic refresh.

    Usage:
        manager = TokenManager(compound_token="refresh|project|managed")
        tokens = await manager.get_valid_tokens()
    """

    def __init__(
        self,
        compound_token: Optional[str] = None,
        tokens: Optional[OAuthTokens] = None,
    ):
        """
        Initialize TokenManager.

        Args:
            compound_token: Compound refresh token string
            tokens: Pre-existing OAuthTokens object
        """
        self._compound_token = compound_token
        self._tokens = tokens
        self._refresh_lock = None  # Lazy init for async lock

    @property
    def has_tokens(self) -> bool:
        """Check if we have any tokens (valid or not)."""
        return self._tokens is not None or self._compound_token is not None

    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid, non-expired tokens."""
        return self._tokens is not None and not self._tokens.is_expired

    async def get_valid_tokens(self, force_refresh: bool = False) -> OAuthTokens:
        """
        Get valid tokens, refreshing if necessary.

        Args:
            force_refresh: Force token refresh even if not expired (e.g., after 401)

        Returns:
            OAuthTokens with valid access token

        Raises:
            ValueError: If no tokens available or refresh fails
        """
        import asyncio

        # Lazy init async lock
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()

        async with self._refresh_lock:
            # Check if we have valid tokens (skip if force_refresh)
            if not force_refresh and self._tokens and not self._tokens.is_expired:
                logger.debug(f"Using cached token (expires_at: {self._tokens.expires_at.isoformat()})")
                return self._tokens

            # Log why we're refreshing
            if force_refresh:
                logger.info("Force refresh requested (likely due to 401)")
            elif self._tokens:
                logger.info(f"Token expired (expires_at: {self._tokens.expires_at.isoformat()}, now: {datetime.now(timezone.utc).isoformat()})")
            else:
                logger.info("No cached tokens, refreshing from compound token")

            # Need to refresh
            if self._tokens:
                # Use existing refresh token
                compound = self._tokens.refresh_token
                if self._tokens.project_id != DEFAULT_PROJECT_ID:
                    compound = f"{compound}|{self._tokens.project_id}"
                    if self._tokens.managed_project_id:
                        compound = f"{compound}|{self._tokens.managed_project_id}"
                logger.debug(f"Refreshing with project_id: {self._tokens.project_id}")
            elif self._compound_token:
                compound = self._compound_token
                logger.debug("Refreshing with compound token")
            else:
                raise ValueError("No tokens or compound token available for refresh")

            try:
                self._tokens = await refresh_access_token(compound)
                logger.info(f"Token refresh successful. New expiry: {self._tokens.expires_at.isoformat()}")

                # Auto-save refreshed tokens to disk
                save_tokens(self._tokens)
                logger.info("Refreshed tokens saved to disk")

            except Exception as e:
                logger.error(f"Token refresh failed: {e}")
                raise

            return self._tokens

    def set_tokens(self, tokens: OAuthTokens) -> None:
        """Set tokens directly (e.g., after initial OAuth flow)."""
        self._tokens = tokens

    def clear(self) -> None:
        """Clear all stored tokens."""
        self._tokens = None
        self._compound_token = None


def load_tokens() -> Optional[OAuthTokens]:
    """Load tokens from persistent storage."""
    try:
        if TOKENS_FILE.exists():
            data = json.loads(TOKENS_FILE.read_text())
            tokens = OAuthTokens.from_dict(data)
            logger.info(f"Loaded tokens from {TOKENS_FILE}")
            return tokens
    except Exception as e:
        logger.warning(f"Failed to load tokens: {e}")
    return None


def save_tokens(tokens: OAuthTokens) -> None:
    """Save tokens to persistent storage."""
    try:
        TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKENS_FILE.write_text(json.dumps(tokens.to_dict(), indent=2))
        try:
            os.chmod(TOKENS_FILE, 0o600)
        except OSError:
            pass  # DrvFS may not honour chmod; CI/Linux target is 0600.
        logger.info(f"Saved tokens to {TOKENS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save tokens: {e}")


def logout() -> None:
    """Disconnect the Antigravity provider: delete the stored tokens. No-op when
    absent; never raises."""
    try:
        if TOKENS_FILE.is_file():
            TOKENS_FILE.unlink()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"antigravity logout: could not delete tokens: {type(e).__name__}")
