"""Saved proxy preferences for the SASE-style corporate-proxy toggle.

The file lives at ``~/.olga_copilot/proxy.json`` next to the other sign-in
records. Validators refuse the few ways a help-desk paste can reasonably
land in the wrong shape (a scheme in the host, a port outside the TCP range).
A corrupt or missing file reads as defaults, so the app never falls over on
first run or on a partial write.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from olga_companion.config import private_state_root

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")


@dataclass(frozen=True)
class ProxyPrefs:
    enabled: bool
    host: str
    port: int
    probe_target: str
    probe_port: int


_DEFAULTS = ProxyPrefs(
    enabled=False,
    host="127.0.0.1",
    port=8888,
    probe_target="api.openai.com",
    probe_port=443,
)


def _file() -> Path:
    return private_state_root() / "proxy.json"


def _validate(prefs: ProxyPrefs) -> None:
    for label, value in (("host", prefs.host), ("probe_target", prefs.probe_target)):
        if not _HOST_RE.match(value):
            raise ValueError(f"invalid {label}: {value!r}")
    for label, value in (("port", prefs.port), ("probe_port", prefs.probe_port)):
        if not (1 <= int(value) <= 65535):
            raise ValueError(f"invalid {label}: {value!r}")


def load() -> ProxyPrefs:
    path = _file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _DEFAULTS
    if not isinstance(raw, dict):
        return _DEFAULTS
    candidate = ProxyPrefs(
        enabled=bool(raw.get("enabled", _DEFAULTS.enabled)),
        host=str(raw.get("host", _DEFAULTS.host)),
        port=int(raw.get("port", _DEFAULTS.port)),
        probe_target=str(raw.get("probe_target", _DEFAULTS.probe_target)),
        probe_port=int(raw.get("probe_port", _DEFAULTS.probe_port)),
    )
    try:
        _validate(candidate)
    except ValueError:
        return _DEFAULTS
    return candidate


def save(prefs: ProxyPrefs) -> None:
    _validate(prefs)
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".proxy-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(prefs), fh)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
