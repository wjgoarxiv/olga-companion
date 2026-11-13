"""Sidecar routes for the Settings → Support diagnostics bundle.

Previews and writes a zip the user attaches to a GitHub issue when the app
misbehaves on another machine. The preview is a plain read of version strings,
the current proxy summary (no credentials) and the recent sidecar log files;
the bundle write packs those same facts into a zip in a local temp directory,
and returns the path plus a pre-filled GitHub new-issue URL.

Credentials never enter the preview or the bundle: the proxy summary is read
from ``net.preferences`` (host, port, probe target, enabled, last probe), and
the log files come from ``runtime_logging``'s rotating handler, which already
redacts authorization headers. API keys, tokens, passwords and the updater
signing key are never read here.
"""

from __future__ import annotations

import datetime as _dt
import json
import platform
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from olga_companion import __version__ as app_version
from olga_companion.agent import session_token
from olga_companion.config import load_llm_selection, project_root
from olga_companion.net import http as net_http
from olga_companion.net import preferences

_ISSUE_BASE = "https://github.com/wjgoarxiv/olga-companion/issues/new"


def _require_session_token(token: str | None) -> None:
    if not session_token.verify(token):
        raise HTTPException(status_code=401, detail="Missing or invalid session token.")


def _logs_dir() -> Path:
    return project_root() / "var" / "logs"


def _bundles_dir() -> Path:
    return Path(tempfile.gettempdir()) / "olga-companion-diagnostics"


def _list_logs() -> list[dict[str, Any]]:
    directory = _logs_dir()
    if not directory.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not path.name.startswith("sidecar.log"):
            continue
        stat = path.stat()
        entries.append({
            "name": path.name,
            "size_bytes": stat.st_size,
            "mtime": _dt.datetime.fromtimestamp(stat.st_mtime, tz=_dt.timezone.utc)
                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return entries


def _exe_globs() -> list[str]:
    """Glob patterns scanned for OLGA installs (seam for tests)."""
    from olga_companion import olga_runtime_paths

    return list(olga_runtime_paths.DEFAULT_OLGA_EXE_GLOBS)


def _olga_versions() -> list[dict[str, str]]:
    """Detected OLGA installs as version+kind only — never paths.

    Reuses the cached run detection (shared exclusions, registry, manual
    override) instead of a second scan implementation.
    """
    try:
        from olga_companion import olga_runtime_detection as detection
    except ImportError:
        return []
    try:
        found = detection.detect_olga(_exe_globs())
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — diagnostics is fail-soft
        return []
    if not isinstance(found, dict):
        return []
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for item in found.get("candidates", []):
        if not isinstance(item, dict):
            continue
        version = item.get("version") or "unknown"
        kind = item.get("kind") or "executable"
        if not isinstance(version, str) or not isinstance(kind, str):
            continue
        seen[(version, kind)] = {"version": version, "kind": kind}
    return sorted(
        seen.values(),
        key=lambda item: (item["version"] == "unknown", item["version"], item["kind"]),
    )


def _last_ui_locale() -> str | None:
    """Most recent chat-turn locale as a best-effort UI-language signal.

    The sidecar stores no UI preference itself; turns persist their locale,
    so the newest session with one is the honest signal. Bounded and
    credential-free.
    """
    try:
        from olga_companion.agent import history

        sessions = history.list_sessions()
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK — diagnostics is fail-soft
        return None
    ordered = sorted(
        sessions,
        key=lambda item: item.get("updated_ms") or 0,
        reverse=True,
    )
    for session in ordered[:3]:
        session_id = session.get("session_id")
        if not session_id:
            continue
        try:
            records = history.read(str(session_id))
        except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK
            continue
        for record in reversed(records):
            locale = record.get("locale")
            if locale in ("ko", "en"):
                return str(locale)
    return None


def _versions() -> dict[str, str]:
    return {
        "app_version": app_version,
        "python_version": sys.version.split()[0],
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
    }


def _proxy_summary() -> dict[str, Any]:
    saved = preferences.load()
    cached = net_http._cache
    last_probe: dict[str, Any] | None = None
    if cached is not None and cached.result is not None:
        r = cached.result
        last_probe = {
            "ok": r.ok, "status_code": r.status_code,
            "error_kind": r.error_kind, "elapsed_ms": r.elapsed_ms,
        }
    return {
        "enabled": saved.enabled,
        "host": saved.host,
        "port": saved.port,
        "probe_target": saved.probe_target,
        "probe_port": saved.probe_port,
        "last_probe": last_probe,
    }


def _issue_url(versions: dict[str, str], proxy: dict[str, Any]) -> str:
    title = f"[Bug] OLGA Companion {versions['app_version']}"
    body = (
        "<!-- Attach the diagnostics zip the Settings → Support panel created. -->\n\n"
        "## What happened\n\n"
        "<!-- What you tried, what you expected, what you saw. -->\n\n"
        "## Environment\n\n"
        f"- App: {versions['app_version']}\n"
        f"- OS: {versions['os']}\n"
        f"- Python: {versions['python_version']}\n"
        f"- Proxy: {'on' if proxy['enabled'] else 'off'}\n"
    )
    query = urllib.parse.urlencode(
        {"title": title, "body": body, "labels": "bug"},
        quote_via=urllib.parse.quote,
    )
    return f"{_ISSUE_BASE}?{query}"


router = APIRouter()


@router.get("/api/diagnostics")
def preview(x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    _require_session_token(x_session_token)
    return {
        "versions": _versions(),
        "proxy": _proxy_summary(),
        "logs": _list_logs(),
    }


@router.post("/api/diagnostics/bundle")
def bundle(x_session_token: str | None = Header(default=None)) -> dict[str, Any]:
    _require_session_token(x_session_token)
    versions = _versions()
    proxy = _proxy_summary()
    stamp = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _bundles_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"olga-diagnostics-{stamp}.zip"
    meta = {
        "generated_at": _dt.datetime.now(tz=_dt.timezone.utc)
                           .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "versions": versions,
        "proxy": proxy,
        "olga_versions": _olga_versions(),
        "llm_selection": load_llm_selection(),
        "ui_locale": _last_ui_locale(),
    }
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.json", json.dumps(meta, indent=2, ensure_ascii=False))
        for entry in _list_logs():
            src = _logs_dir() / entry["name"]
            try:
                zf.write(src, f"logs/{entry['name']}")
            except OSError:
                continue
    return {
        "bundle_path": str(out_path),
        "size_bytes": out_path.stat().st_size,
        "issue_url": _issue_url(versions, proxy),
    }
