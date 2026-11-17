"""T3 gate — chat history store: round-trip, credential refusal, id validation."""
from __future__ import annotations

import pytest

from olga_companion.agent import history


def test_new_session_round_trip():
    sid = history.new_session("demo")
    recs = history.read(sid)
    assert recs[0]["record"] == "meta"
    assert recs[0]["title"] == "demo"
    history.append(sid, {"record": "user", "text": "hi"})
    history.append(sid, {"record": "assistant", "text": "hello"})
    turns = list(history.iter_turns(sid))
    assert [t["record"] for t in turns] == ["user", "assistant"]


def test_append_refuses_credential_records():
    sid = history.new_session()
    for key in ("access_token", "refresh_token", "api_key", "token", "authorization"):
        with pytest.raises(ValueError, match="credential"):
            history.append(sid, {key: "secret-value", "record": "user"})


def test_invalid_session_id_rejected():
    with pytest.raises(ValueError, match="Invalid session id"):
        history.read("../etc/passwd")
    with pytest.raises(ValueError, match="Invalid session id"):
        history.read("not a hex id")
    # fullmatch closes the trailing-newline hole the $ anchor left open.
    with pytest.raises(ValueError, match="Invalid session id"):
        history.read("abc123abc123\n")


def test_append_to_unknown_session_rejected():
    with pytest.raises(ValueError, match="Unknown session"):
        history.append("deadbeefdeadbeef", {"record": "user", "text": "x"})


def test_list_sessions_includes_new(tmp_path, monkeypatch):
    sid = history.new_session("listed")
    listed = {s["session_id"]: s for s in history.list_sessions()}
    assert sid in listed
    assert listed[sid]["title"] == "listed"
