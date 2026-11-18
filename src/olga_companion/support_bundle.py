"""Read-only support information for an IT ticket: app and OS versions, the OLGA installs
found, and the status codes. No folder paths, case names, values or user names: an OLGA
install is named by its program file only."""
from __future__ import annotations

import platform
from pathlib import PureWindowsPath
from typing import Any

from . import __version__


def _file_name(path: object) -> str:
    return PureWindowsPath(str(path or "")).name


def version_matrix(detection: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per OLGA install found: version, kind, how it was found, and whether the app
    can start it (an engine or a script; another native program is not supported)."""
    selected = detection.get("candidate_id")
    rows = []
    for item in detection.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        rows.append({
            "version": item.get("version"),
            "kind": kind,
            "source": item.get("source"),
            "file": _file_name(item.get("exe")),
            "runnable": kind in ("engine", "script"),
            "selected": bool(selected) and item.get("candidate_id") == selected,
        })
    return rows


def _status(capabilities: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, cap in capabilities.items():
        if not isinstance(cap, dict):
            out[name] = cap
            continue
        params = dict(cap.get("reason_params") or {})
        if "exe" in params:
            params["exe"] = _file_name(params["exe"])
        out[name] = {"enabled": bool(cap.get("enabled")), "reason_code": cap.get("reason_code"), "reason_params": params}
    return out


def support_bundle() -> dict[str, Any]:
    from . import run_queries, runner
    from .sidecar import _all_capabilities

    detection = run_queries.cached_capability_detection(runner._context())
    return {
        "schema": 1,
        "app_version": __version__,
        "os": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": platform.python_version(),
        "olga": version_matrix(detection),
        "capabilities": _status(_all_capabilities()),
    }
