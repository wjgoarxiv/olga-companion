from __future__ import annotations

import hashlib
import errno
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_save_as_absent_destination_race_preserves_concurrent_file_and_cleans_temp(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"approved export")
    destination = chosen / "raced.csv"
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    real_link = sidecar.os.link
    attempts = 0

    def concurrent_create(source_path, destination_path, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        destination.write_bytes(b"concurrent winner")
        return real_link(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(sidecar.os, "link", concurrent_create)
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-absent-race", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert attempts == 1
    assert destination.read_bytes() == b"concurrent winner"
    assert source.read_bytes() == b"approved export"
    assert [path.name for path in chosen.iterdir()] == [destination.name]


def test_save_as_absent_destination_unsupported_no_clobber_fails_without_publish(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"approved export")
    destination = chosen / "unsupported.csv"
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    monkeypatch.setattr(
        sidecar.os,
        "link",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError(errno.EPERM, "hardlinks unsupported")
        ),
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-no-clobber-unsupported", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert not destination.exists()
    assert list(chosen.iterdir()) == []


def test_save_as_existing_destination_race_restores_the_concurrent_winner(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"approved export")
    destination = chosen / "raced.csv"
    destination.write_bytes(b"initial destination")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    real_replace = sidecar._replace_existing_with_prior
    attempts = 0

    def concurrent_replace(source_path, destination_path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            destination.write_bytes(b"concurrent winner")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(sidecar, "_replace_existing_with_prior", concurrent_replace)

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-existing-race", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert attempts == 2
    assert destination.read_bytes() == b"concurrent winner"
    assert source.read_bytes() == b"approved export"
    assert [path.name for path in chosen.iterdir()] == [destination.name]


def test_restore_displaced_hash_mismatch_retains_the_expected_recovery_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    expected = b"concurrent winner"
    destination = tmp_path / "saved.csv"
    destination.write_bytes(b"new export")
    displaced = tmp_path / ".saved.csv.displaced.bak"
    displaced.write_bytes(expected)
    expected_hash = hashlib.sha256(expected).hexdigest()
    real_replace = sidecar._replace_existing_with_prior

    def mutate_after_restore(source_path: Path, destination_path: Path) -> Path:
        discarded = real_replace(source_path, destination_path)
        destination.write_bytes(b"external mutation after restore")
        return discarded

    monkeypatch.setattr(sidecar, "_replace_existing_with_prior", mutate_after_restore)

    with pytest.raises(sidecar.SaveAsRecoveryRequiredError) as raised:
        sidecar._restore_displaced(displaced, destination, expected_hash)

    recovery = raised.value.backup_path
    assert recovery.is_file()
    assert recovery.read_bytes() == expected
    assert (
        hashlib.sha256(recovery.read_bytes()).hexdigest() == raised.value.expected_hash
    )
