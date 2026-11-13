"""HTTP client factories for the LLM provider layer.

Every provider call goes through these factories so that one place decides
whether to route the request through a corporate proxy. With the toggle off
the factories behave exactly like direct ``httpx.Client`` / ``aiohttp.ClientSession``
construction, which is what the adapters depended on before this module existed.

Later tasks wire ``proxy_url()`` to the saved preferences and the probe cache;
task 1 only lands the seam.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import aiohttp
import httpx

from olga_companion.net import preferences, proxy_probe


@dataclass(frozen=True)
class _CachedProbe:
    """What the last probe said and the preferences it was run against.

    When the preferences change, the cache is dropped — a stale success for a
    previous `host:port` must not keep the proxy on under the new values.
    """

    prefs_key: tuple
    result: proxy_probe.ProbeResult


_cache: _CachedProbe | None = None
_lock = threading.Lock()


def _key(prefs: preferences.ProxyPrefs) -> tuple:
    return (prefs.host, prefs.port, prefs.probe_target, prefs.probe_port)


def set_probe_result(result: proxy_probe.ProbeResult) -> None:
    """Record the last probe so future `proxy_url()` reads can use it.

    The current preferences shape the cache key; a later preferences change
    makes the cached entry stale and `proxy_url()` returns None until the
    settings panel or startup runs the probe again.
    """
    global _cache
    prefs_now = preferences.load()
    with _lock:
        _cache = _CachedProbe(prefs_key=_key(prefs_now), result=result)


def clear_probe_cache() -> None:
    """Drop the cached probe. Test helper and a hook for prefs-change paths."""
    global _cache
    with _lock:
        _cache = None


def proxy_url() -> str | None:
    """The proxy URL to route outbound provider requests through, or None.

    Returns None unless the toggle is on and the last probe against the
    current host/port said OK. No probing happens here: the request path
    must not pay for a round-trip on every call.
    """
    prefs_now = preferences.load()
    if not prefs_now.enabled:
        return None
    with _lock:
        cached = _cache
    if cached is None or cached.prefs_key != _key(prefs_now) or not cached.result.ok:
        return None
    return f"http://{prefs_now.host}:{prefs_now.port}"


async def refresh() -> proxy_probe.ProbeResult | None:
    """Run a fresh probe against the saved preferences and cache the result.

    Called at sidecar startup and from the settings panel. Does nothing when
    the toggle is off, because an OK result on a disabled proxy would be
    misleading and a failure would scare the user for no reason.
    """
    prefs_now = preferences.load()
    if not prefs_now.enabled:
        return None
    result = await proxy_probe.probe(
        prefs_now.host, prefs_now.port,
        prefs_now.probe_target, prefs_now.probe_port,
    )
    set_probe_result(result)
    return result


def _httpx_kwargs(user: dict) -> dict:
    """Inject ``proxy=`` when the toggle is on, without overwriting the caller's value."""
    out = dict(user)
    if "proxy" not in out:
        candidate = proxy_url()
        if candidate:
            out["proxy"] = candidate
    return out


def sync_client(**kwargs) -> httpx.Client:
    return httpx.Client(**_httpx_kwargs(kwargs))


def async_client(**kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(**_httpx_kwargs(kwargs))


def aiohttp_session(**kwargs) -> aiohttp.ClientSession:
    """Return an aiohttp session that injects the proxy toggle on every request.

    aiohttp takes ``proxy=`` per request (not on the session), so the toggle
    has to be re-checked at each call. A caller that passes an explicit
    ``proxy=`` wins. The subclass is built dynamically against the current
    value of ``aiohttp.ClientSession`` so tests that monkeypatch that symbol
    with a fake still see their fake used.
    """
    base = aiohttp.ClientSession

    class _ProxyAwareSession(base):  # type: ignore[valid-type,misc]
        async def _request(self, method, str_or_url, **rkwargs):
            if "proxy" not in rkwargs:
                candidate = proxy_url()
                if candidate:
                    rkwargs["proxy"] = candidate
            return await super()._request(method, str_or_url, **rkwargs)

    return _ProxyAwareSession(**kwargs)
