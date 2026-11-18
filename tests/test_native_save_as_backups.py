from __future__ import annotations

import hashlib
import errno
import os
import re
import stat
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_verified_backup_is_an_independent_fsynced_copy(tmp_path: Path) -> None:
    import olga_companion.sidecar as sidecar

    destination = tmp_path / "existing.csv"
    destination.write_bytes(b"old snapshot")
    expected_hash = hashlib.sha256(destination.read_bytes()).hexdigest()

    backup = sidecar._create_verified_backup(destination, expected_hash)
    try:
        assert backup.read_bytes() == b"old snapshot"
        assert not os.path.samefile(destination, backup)
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    finally:
        backup.unlink(missing_ok=True)


def test_verified_backup_file_fsync_precedes_parent_directory_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    destination = tmp_path / "existing.csv"
    destination.write_bytes(b"old snapshot")
    expected_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    events: list[str] = []
    real_fsync = sidecar.os.fsync

    def record_file_fsync(fd: int):
        events.append("backup-file-fsync")
        return real_fsync(fd)

    monkeypatch.setattr(sidecar.os, "fsync", record_file_fsync)
    monkeypatch.setattr(
        sidecar, "_fsync_directory", lambda parent: events.append("backup-parent-fsync")
    )

    backup = sidecar._create_verified_backup(destination, expected_hash)
    try:
        assert events == ["backup-file-fsync", "backup-parent-fsync"]
    finally:
        backup.unlink(missing_ok=True)


def test_backup_parent_fsync_failure_aborts_before_destination_replace_and_cleans_backup(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"new export")
    destination = chosen / "saved.csv"
    destination.write_bytes(b"old destination")
    destination_replaced = False
    real_replace = sidecar.os.replace

    def observe_replace(source_path, destination_path):
        nonlocal destination_replaced
        if Path(destination_path) == destination:
            destination_replaced = True
        return real_replace(source_path, destination_path)

    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    monkeypatch.setattr(sidecar.os, "replace", observe_replace)
    monkeypatch.setattr(
        sidecar,
        "_fsync_directory",
        lambda parent: (_ for _ in ()).throw(
            OSError(errno.EIO, "backup parent fsync failed")
        ),
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-backup-dir-fsync-fail", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert destination_replaced is False
    assert destination.read_bytes() == b"old destination"
    assert source.read_bytes() == b"new export"
    assert [path.name for path in chosen.iterdir()] == [destination.name]


def test_concurrent_destination_mutation_aborts_before_replace_and_preserves_snapshot_backup(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "private-parent-name"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"new export")
    destination = chosen / "private-destination-name.csv"
    destination.write_bytes(b"old snapshot")
    captured_backups: list[Path] = []
    backup_parent_fsyncs: list[Path] = []
    real_create = sidecar._create_verified_backup

    def create_then_mutate(path: Path, expected_hash: str) -> Path:
        backup = real_create(path, expected_hash)
        captured_backups.append(backup)
        path.write_bytes(b"concurrent current bytes")
        return backup

    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    monkeypatch.setattr(
        sidecar,
        "_fsync_directory",
        lambda parent: backup_parent_fsyncs.append(Path(parent)),
    )
    monkeypatch.setattr(sidecar, "_create_verified_backup", create_then_mutate)

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-concurrent-mutation", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "save_as_recovery_required"
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", detail["recovery_id"])
    assert destination.read_bytes() == b"concurrent current bytes"
    assert source.read_bytes() == b"new export"
    assert len(captured_backups) == 1
    assert backup_parent_fsyncs == [chosen]
    backup = captured_backups[0]
    assert backup.is_file() and backup.read_bytes() == b"old snapshot"
    assert not os.path.samefile(destination, backup)
    public = response.text
    assert str(tmp_path) not in public
    assert chosen.name not in public
    assert destination.name not in public
    assert backup.name not in public
