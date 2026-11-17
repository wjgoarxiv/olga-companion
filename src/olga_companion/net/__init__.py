"""Shared network helpers: one proxy seam for every LLM provider request."""

from olga_companion.net.http import (
    aiohttp_session,
    async_client,
    clear_probe_cache,
    proxy_url,
    refresh,
    set_probe_result,
    sync_client,
)

__all__ = [
    "aiohttp_session",
    "async_client",
    "clear_probe_cache",
    "proxy_url",
    "refresh",
    "set_probe_result",
    "sync_client",
]
