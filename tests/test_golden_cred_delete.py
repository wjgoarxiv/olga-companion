"""R12: a failed Windows credential delete must not be reported as success."""

import ctypes

import pytest

from olga_companion.llm import api_key_connections as conn


class _FailingAdvapi:
    def CredDeleteW(self, *_args):  # noqa: N802 - Win32 name
        return 0


def _fail_with(monkeypatch, code: int) -> None:
    monkeypatch.setattr(conn, "_advapi32", _FailingAdvapi)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: code, raising=False)


def test_advapi32_is_loaded_with_last_error_tracking(monkeypatch):
    seen = {}

    def fake_windll(name, **kwargs):
        seen["name"] = name
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(ctypes, "WinDLL", fake_windll, raising=False)
    conn._advapi32()
    assert seen.get("use_last_error") is True


@pytest.mark.parametrize("code", [0, 5])
def test_failed_delete_raises(monkeypatch, code):
    _fail_with(monkeypatch, code)
    with pytest.raises(OSError):
        conn._cred_delete("OLGA Companion/apikey/x")


@pytest.mark.parametrize("code", [2, 1168])
def test_missing_credential_is_not_an_error(monkeypatch, code):
    _fail_with(monkeypatch, code)
    conn._cred_delete("OLGA Companion/apikey/x")
