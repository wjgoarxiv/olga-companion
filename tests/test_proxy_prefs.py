"""Proxy preferences round-trip through ``~/.olga_copilot/proxy.json``.

Defaults match the enterprise-proxy guide's canonical values: off, with
``127.0.0.1:8888`` and ``api.openai.com:443`` as the probe target. A malformed
file reads as defaults; writes are atomic and the field validators refuse the
few formats a corporate help desk could reasonably paste wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from olga_companion.net import preferences as prefs


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(prefs, "_file", lambda: tmp_path / "proxy.json")
    return tmp_path / "proxy.json"


def test_defaults_are_off_with_the_guide_host_and_port(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    loaded = prefs.load()
    assert loaded == prefs.ProxyPrefs(
        enabled=False, host="127.0.0.1", port=8888,
        probe_target="api.openai.com", probe_port=443,
    )


def test_save_then_load_round_trips(tmp_path: Path, monkeypatch) -> None:
    path = _isolate(tmp_path, monkeypatch)
    prefs.save(prefs.ProxyPrefs(enabled=True, host="proxy.local", port=3128,
                                probe_target="api.anthropic.com", probe_port=443))
    assert json.loads(path.read_text(encoding="utf-8"))["enabled"] is True
    assert prefs.load().host == "proxy.local"


def test_an_invalid_host_is_refused(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="host"):
        prefs.save(prefs.ProxyPrefs(enabled=True, host="not valid!", port=8888,
                                    probe_target="api.openai.com", probe_port=443))


def test_an_out_of_range_port_is_refused(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="port"):
        prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=0,
                                    probe_target="api.openai.com", probe_port=443))


def test_an_unreadable_file_reads_as_defaults(tmp_path: Path, monkeypatch) -> None:
    path = _isolate(tmp_path, monkeypatch)
    path.write_text("{ not json", encoding="utf-8")
    assert prefs.load() == prefs.ProxyPrefs(
        enabled=False, host="127.0.0.1", port=8888,
        probe_target="api.openai.com", probe_port=443,
    )


def test_a_file_with_an_unknown_field_still_loads(tmp_path: Path, monkeypatch) -> None:
    path = _isolate(tmp_path, monkeypatch)
    path.write_text(json.dumps({"enabled": True, "host": "127.0.0.1", "port": 8888,
                                "probe_target": "api.openai.com", "probe_port": 443,
                                "future_knob": "ignore me"}), encoding="utf-8")
    assert prefs.load().enabled is True


def test_save_is_atomic_and_leaves_no_temp_siblings(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    prefs.save(prefs.ProxyPrefs(enabled=True, host="127.0.0.1", port=8888,
                                probe_target="api.openai.com", probe_port=443))
    assert (tmp_path / "proxy.json").is_file()
    leftovers = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".proxy-"))
    assert leftovers == [], f"atomic save left a temp file behind: {leftovers}"


def test_an_https_scheme_in_host_is_refused(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="host"):
        prefs.save(prefs.ProxyPrefs(enabled=True, host="https://127.0.0.1", port=8888,
                                    probe_target="api.openai.com", probe_port=443))
