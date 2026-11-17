"""history.delete — removes a chat's JSONL, refuses traversal ids, idempotent."""
import pytest

from olga_companion.agent import history


@pytest.fixture
def chats(tmp_path, monkeypatch):
    monkeypatch.setattr(history.config, "project_root", lambda: tmp_path)
    return tmp_path


def test_delete_removes_the_session(chats):
    sid = history.new_session("t")
    assert any(s["session_id"] == sid for s in history.list_sessions())
    assert history.delete(sid) is True
    assert not any(s["session_id"] == sid for s in history.list_sessions())


def test_delete_is_idempotent(chats):
    sid = history.new_session("t")
    assert history.delete(sid) is True
    assert history.delete(sid) is False  # already gone


def test_delete_missing_valid_id_is_false(chats):
    assert history.delete("abcdef012345") is False  # well-formed id, no file


def test_delete_refuses_traversal_id(chats):
    with pytest.raises(ValueError):
        history.delete("../etc/passwd")
    with pytest.raises(ValueError):
        history.delete("..")
