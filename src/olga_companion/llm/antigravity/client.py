"""Antigravity API client for OlgaCopilot."""

import logging
import uuid
import asyncio
from datetime import datetime
from typing import Callable, Optional

import aiohttp

from .constants import (
    DAILY_ENDPOINT,
    PROD_ENDPOINT,
    STREAM_PATH,
    STREAM_PARAMS,
    HEADERS,
    RATE_LIMIT_RETRY_AFTER,
    MAX_RETRIES,
)
from .token import OAuthTokens, TokenManager, refresh_access_token
from .streaming import parse_stream, convert_tools_to_antigravity

logger = logging.getLogger(__name__)


class AntigravityClient:
    """
    Client for Antigravity API with automatic token refresh and endpoint fallback.

    Usage:
        client = AntigravityClient(
            access_token="...",
            refresh_token="...",
            project_id="rising-fact-p41fc",
            expires_at=datetime.now() + timedelta(hours=1),
        )

        async for chunk in client.stream_generate("gemini-3-pro", contents):
            print(chunk["text"], end="")
    """

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        project_id: str,
        expires_at: datetime,
        managed_project_id: Optional[str] = None,
    ):
        """
        Initialize AntigravityClient.

        Args:
            access_token: Valid OAuth access token
            refresh_token: Refresh token for auto-refresh
            project_id: Antigravity project ID
            expires_at: Token expiration datetime
            managed_project_id: Optional managed project ID
        """
        self._tokens = OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            project_id=project_id,
            managed_project_id=managed_project_id,
        )
        self._token_manager = TokenManager(tokens=self._tokens)
        self._session: Optional[aiohttp.ClientSession] = None
        self._current_endpoint = DAILY_ENDPOINT

    @classmethod
    def from_tokens(cls, tokens: OAuthTokens) -> "AntigravityClient":
        """Create client from OAuthTokens object."""
        return cls(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            project_id=tokens.project_id,
            expires_at=tokens.expires_at,
            managed_project_id=tokens.managed_project_id,
        )

    @classmethod
    async def from_compound_token(cls, compound_token: str) -> "AntigravityClient":
        """
        Create client from compound token string.

        Args:
            compound_token: Format "refresh_token|projectId|managedProjectId"

        Returns:
            AntigravityClient with fresh tokens
        """
        tokens = await refresh_access_token(compound_token)
        return cls.from_tokens(tokens)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "AntigravityClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _ensure_valid_token(self, force_refresh: bool = False) -> str:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Args:
            force_refresh: Force token refresh even if not expired (e.g., after 401)

        Returns:
            Valid access token
        """
        tokens = await self._token_manager.get_valid_tokens(force_refresh=force_refresh)
        self._tokens = tokens
        return tokens.access_token

    def _build_headers(self, access_token: str) -> dict:
        """
        Build request headers with authorization.

        Args:
            access_token: Valid OAuth access token

        Returns:
            Headers dict
        """
        headers = HEADERS.copy()
        headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def _build_envelope(
        self,
        model: str,
        request_body: dict,
    ) -> dict:
        """
        Wrap request in Antigravity envelope format.

        Args:
            model: Model name (e.g., "gemini-3-pro")
            request_body: Inner request with contents, systemInstruction, etc.

        Returns:
            Antigravity envelope dict
        """
        return {
            "project": self._tokens.project_id,
            "model": model,
            "request": request_body,
            "userAgent": "antigravity",
            "requestId": str(uuid.uuid4()),
        }

    def _build_request_body(
        self,
        contents: list[dict],
        system_instruction: Optional[str] = None,
        tools: Optional[list] = None,
        generation_config: Optional[dict] = None,
        model: Optional[str] = None,
        tool_config: Optional[dict] = None,
    ) -> dict:
        """
        Build inner request body for Antigravity API.

        Args:
            contents: List of message dicts with role and parts
            system_instruction: System prompt text
            tools: List of function declarations
            generation_config: Generation parameters
            model: Model name for model-family-specific adjustments
            tool_config: Optional tool configuration (e.g., {"functionCallingConfig": {"mode": "ANY"}})

        Returns:
            Request body dict
        """
        body = {
            "contents": contents,
        }

        # System instruction MUST be in parts format
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        # Generation config - strip unsupported fields based on model family
        if generation_config:
            clean_config = self._clean_generation_config(generation_config, model)
            body["generationConfig"] = clean_config
        else:
            body["generationConfig"] = {
                "maxOutputTokens": 4096,
                "temperature": 0.7,
            }

        # Tools in functionDeclarations format
        if tools:
            converted_tools = convert_tools_to_antigravity(tools)
            body["tools"] = [{
                "functionDeclarations": converted_tools
            }]

        # Tool config (e.g., force tool calling with mode: ANY)
        if tool_config and tools:
            body["toolConfig"] = tool_config

        return body

    def _clean_generation_config(self, config: dict, model: Optional[str]) -> dict:
        """
        Clean generation_config by removing fields unsupported by the target model family.

        Different model families support different generation config fields:
        - Gemini: supports thinking_config, response_modalities, etc.
        - GPT-OSS: only supports basic fields (temperature, maxOutputTokens, topP, topK)
        - Claude: only supports basic fields (temperature, maxOutputTokens, topP, topK)

        Args:
            config: Raw generation config dict
            model: Model name (e.g., "gemini-3-flash", "gpt-oss-120b-medium", "claude-sonnet-4-5")

        Returns:
            Cleaned generation config with only supported fields
        """
        if not model:
            # No model specified - return basic fields only (safest)
            return {k: v for k, v in config.items() if k in {
                "temperature", "maxOutputTokens", "topP", "topK"
            }}

        model_lower = model.lower()

        # Gemini models - support extended fields
        if "gemini" in model_lower:
            # Gemini supports all fields, no filtering needed
            return config

        # GPT-OSS models - only basic fields
        elif "gpt" in model_lower:
            return {k: v for k, v in config.items() if k in {
                "temperature", "maxOutputTokens", "topP", "topK"
            }}

        # Claude models - only basic fields
        elif "claude" in model_lower:
            return {k: v for k, v in config.items() if k in {
                "temperature", "maxOutputTokens", "topP", "topK"
            }}

        # Unknown model - return basic fields only (safest)
        else:
            logger.warning(f"Unknown model family '{model}', using basic generation_config fields only")
            return {k: v for k, v in config.items() if k in {
                "temperature", "maxOutputTokens", "topP", "topK"
            }}

    async def stream_generate(
        self,
        model: str,
        contents: list[dict],
        system_instruction: Optional[str] = None,
        tools: Optional[list] = None,
        generation_config: Optional[dict] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[dict], None]] = None,
        on_usage: Optional[Callable[[dict], None]] = None,
        tool_config: Optional[dict] = None,
    ) -> dict:
        """
        Stream generate content from Antigravity API.

        Args:
            model: Model name (e.g., "gemini-3-pro", "claude-sonnet-4-5")
            contents: Message history with role ("user" or "model") and parts
            system_instruction: System prompt text
            tools: Optional list of function declarations
            generation_config: Optional generation parameters
            on_token: Callback for each text token
            on_thinking: Callback for thinking/reasoning text (GPT-OSS style)
            on_tool_call: Callback for each function call
            on_usage: Callback for usage metadata
            tool_config: Optional tool config (e.g., {"functionCallingConfig": {"mode": "ANY"}} to force tool calls)

        Returns:
            Accumulated response dict with text, thinking, tool_calls, usage

        Raises:
            aiohttp.ClientError: On HTTP errors
            ValueError: On invalid response format
        """
        access_token = await self._ensure_valid_token()

        request_body = self._build_request_body(
            contents=contents,
            system_instruction=system_instruction,
            tools=tools,
            generation_config=generation_config,
            model=model,
            tool_config=tool_config,
        )

        envelope = self._build_envelope(model, request_body)
        headers = self._build_headers(access_token)

        session = await self._get_session()

        # Try endpoints with fallback
        endpoints = [DAILY_ENDPOINT, PROD_ENDPOINT]
        if self._current_endpoint == PROD_ENDPOINT:
            endpoints = [PROD_ENDPOINT, DAILY_ENDPOINT]

        last_error = None

        # Retry loop: ONE short retry for transient 429, raise on second hit
        _429_seen = False
        for retry in range(MAX_RETRIES + 1):
            for attempt, endpoint in enumerate(endpoints):
                url = f"{endpoint}{STREAM_PATH}?{STREAM_PARAMS}"

                try:
                    logger.debug(f"Streaming request to {endpoint} (retry={retry})")

                    async with session.post(
                        url,
                        json=envelope,
                        headers=headers,
                    ) as response:

                        # Handle rate limiting — fast-fail strategy
                        # One short retry (2s) for transient 429s, raise on second hit
                        if response.status == 429:
                            retry_after = int(response.headers.get("Retry-After", RATE_LIMIT_RETRY_AFTER))

                            if not _429_seen and retry < MAX_RETRIES:
                                # First 429 — one short retry with exponential backoff
                                _429_seen = True
                                wait = 2.0  # Short retry delay before model switch
                                logger.warning(f"Rate limited (transient). Short retry in {wait:.1f}s...")
                                await asyncio.sleep(wait)
                                break  # Break inner loop to retry
                            else:
                                # Second 429 or last retry — raise immediately for model switch
                                logger.warning(f"Rate limited on '{model}'. Raising for model switch.")
                                raise aiohttp.ClientResponseError(
                                    response.request_info,
                                    response.history,
                                    status=429,
                                    message=f"Rate limited. Retry after {retry_after}s. Consider switching models.",
                                )

                        # Handle 401 Unauthorized - token may be expired
                        if response.status == 401:
                            error_text = await response.text()
                            logger.warning(f"Got 401 Unauthorized. Attempting token refresh... Error: {error_text[:200]}")

                            # Force token refresh and retry once
                            if retry == 0:  # Only try refresh once
                                try:
                                    access_token = await self._ensure_valid_token(force_refresh=True)
                                    headers = self._build_headers(access_token)
                                    logger.info("Token refreshed successfully, retrying request...")
                                    # Continue to next retry iteration with refreshed token
                                    break  # Break inner loop to trigger retry
                                except Exception as refresh_error:
                                    logger.error(f"Token refresh failed: {refresh_error}")
                                    raise ValueError(
                                        f"Authentication failed. Token refresh failed: {refresh_error}. "
                                        "Please re-authenticate via the app's AI provider panel."
                                    )
                            else:
                                raise ValueError(
                                    "Authentication failed after token refresh. "
                                    "Please re-authenticate via the app's AI provider panel."
                                )

                        # Handle other errors
                        if response.status != 200:
                            error_text = await response.text()

                            # Enhanced logging for 400 Bad Request (common with wrong generation_config)
                            if response.status == 400:
                                logger.error(
                                    f"400 Bad Request for model '{model}'. "
                                    f"This usually means the request format is incompatible with the model. "
                                    f"Error response: {error_text[:1000]}"
                                )
                                # Log the request envelope (without sensitive data) for debugging
                                debug_envelope = {
                                    "model": model,
                                    "request_keys": list(request_body.keys()),
                                    "has_tools": "tools" in request_body,
                                    "has_systemInstruction": "systemInstruction" in request_body,
                                    "generationConfig": request_body.get("generationConfig", {}),
                                }
                                logger.debug(f"Request envelope (debug): {debug_envelope}")

                                # Detect quota/capacity 400s — raise with "quota" keyword
                                # so callers can distinguish from schema errors
                                error_lower = error_text.lower()
                                if any(kw in error_lower for kw in [
                                    "quota", "limit", "exhausted", "capacity",
                                    "overloaded", "resource", "billing",
                                ]):
                                    raise aiohttp.ClientResponseError(
                                        response.request_info,
                                        response.history,
                                        status=400,
                                        message=f"Quota/capacity error for model '{model}': {error_text[:300]}",
                                    )
                            else:
                                logger.error(f"API error {response.status}: {error_text[:500]}")

                            # Try fallback endpoint on 4xx/5xx
                            if attempt < len(endpoints) - 1:
                                logger.info("Trying fallback endpoint...")
                                continue

                            response.raise_for_status()

                        # Success - remember this endpoint
                        self._current_endpoint = endpoint

                        # Parse SSE stream
                        async def response_iterator():
                            async for chunk in response.content.iter_any():
                                yield chunk

                        result = await parse_stream(
                            response_iterator(),
                            on_token=on_token,
                            on_thinking=on_thinking,
                            on_tool_call=on_tool_call,
                            on_usage=on_usage,
                        )

                        return result

                except aiohttp.ClientError as e:
                    last_error = e
                    # Check if it's a rate limit error (ClientResponseError with status 429)
                    is_rate_limit = isinstance(e, aiohttp.ClientResponseError) and e.status == 429

                    # For other errors, try fallback endpoint
                    if attempt < len(endpoints) - 1 and not is_rate_limit:
                        logger.warning(f"Request to {endpoint} failed: {e}. Trying fallback...")
                        continue
                    # If it's rate limit error and we broke from inner loop, continue outer retry loop
                    if is_rate_limit and retry < MAX_RETRIES:
                        break  # Break to outer loop for retry
                    raise
            else:
                # Inner loop completed without break (no 429), exit retry loop
                break

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise RuntimeError("No endpoints available")

    async def generate(
        self,
        model: str,
        contents: list[dict],
        system_instruction: Optional[str] = None,
        tools: Optional[list] = None,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """
        Non-streaming generate (collects full response).

        Args:
            Same as stream_generate

        Returns:
            Complete response dict with text, tool_calls, usage
        """
        return await self.stream_generate(
            model=model,
            contents=contents,
            system_instruction=system_instruction,
            tools=tools,
            generation_config=generation_config,
        )

    @property
    def project_id(self) -> str:
        """Get current project ID."""
        return self._tokens.project_id

    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid tokens."""
        return self._token_manager.is_authenticated
