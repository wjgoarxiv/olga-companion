"""A reveal id opens only a file this app just saved."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from olga_companion import config, native_dialogs, saved_reveal

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_reveal_refuses_any_path_that_was_not_just_saved(tmp_path: Path) -> None:
    other = tmp_path / "other.md"
    other.write_text("not saved by the app", encoding="utf-8")

    assert saved_reveal.path_for_reveal("a" * 32) is None
    assert saved_reveal.path_for_reveal(str(other)) is None
    assert saved_reveal.path_for_reveal(str(other.resolve())) is None


def test_save_as_records_a_reveal_id_without_returning_the_path(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    source = exports / "findings.md"
    source.write_text("# report\n", encoding="utf-8")
    destination = tmp_path / "chosen" / "kept.md"
    destination.parent.mkdir()
    monkeypatch.setattr(config, "exports_root", lambda: exports)
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "reveal-save", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["basename"] == destination.name
    assert str(destination) not in response.text
    reveal_id = body["reveal_id"]
    assert saved_reveal.path_for_reveal(reveal_id) == destination.resolve()
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
