from __future__ import annotations

import errno
import os
import re
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


def test_save_as_temp_replace_observes_original_destination_still_present(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_text("new data")
    destination = chosen / "saved.csv"
    destination.write_text("old data")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    observed_original: list[bytes | None] = []

    def fail_temp_replace(source_path, destination_path):
        observed_original.append(
            destination.read_bytes() if destination.exists() else None
        )
        raise OSError(errno.EIO, "temp replace failed")

    monkeypatch.setattr(sidecar, "_replace_existing_with_prior", fail_temp_replace)

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-original-present", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert source.read_text() == "new data"
    assert destination.read_text() == "old data"
    assert observed_original == [b"old data"], (
        "original must remain until atomic replacement"
    )


def test_save_as_private_cleanup_failure_keeps_published_destination_and_recovery(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_text("new data")
    destination = chosen / "saved.csv"
    destination.write_text("old data")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    real_replace = os.replace
    failed = False

    def fail_cleanup_capture(source: Path, target: Path) -> None:
        nonlocal failed
        if (
            Path(target).parent.name.startswith(".olga-companion-retained-")
            and not failed
        ):
            failed = True
            raise OSError(errno.EIO, "cleanup capture failed")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_cleanup_capture)

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-backup-unlink-fail", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert source.read_text() == "new data"
    assert destination.read_text() == "new data"
    retained = [path for path in chosen.iterdir() if path != destination]
    assert any(path.read_text() == "old data" for path in retained)
    assert all(path.name.startswith(".") for path in retained)
    assert all(path.name not in response.text for path in retained)


def test_post_publish_fsync_failure_never_rolls_back_or_deletes_recovery(
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
    events: list[str] = []
    directory_fsync_calls = 0
    real_unlink = Path.unlink

    def ordered_directory_fsync(parent: Path):
        nonlocal directory_fsync_calls
        directory_fsync_calls += 1
        if directory_fsync_calls == 1:
            events.append("backup-parent-fsync")
            return
        if directory_fsync_calls == 2:
            events.append("new-destination-parent-fsync-failed")
            raise OSError(errno.EIO, "post-replace fsync failed")
        events.append("restored-destination-parent-fsync")

    def record_backup_delete(path: Path, *args, **kwargs):
        if path.suffix == ".bak":
            events.append("backup-delete")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    monkeypatch.setattr(sidecar, "_fsync_directory", ordered_directory_fsync)
    monkeypatch.setattr(Path, "unlink", record_backup_delete)

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-rollback-fsync-order", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert destination.read_bytes() == b"new export"
    assert source.read_bytes() == b"new export"
    assert events == [
        "backup-parent-fsync",
        "new-destination-parent-fsync-failed",
    ]
    retained = [path for path in chosen.iterdir() if path != destination]
    assert any(path.read_bytes() == b"old destination" for path in retained)
    assert all(path.name.startswith(".") for path in retained)


@pytest.mark.parametrize("fallback_fails", [False, True])
def test_post_publish_failure_never_attempts_unsafe_restore_and_retains_backup(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fallback_fails: bool
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_text("new data")
    destination = chosen / "saved.csv"
    old_bytes = b"irreplaceable old data"
    destination.write_bytes(old_bytes)
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    directory_fsync_calls = 0

    def fail_only_post_replace(parent: Path):
        nonlocal directory_fsync_calls
        directory_fsync_calls += 1
        if directory_fsync_calls == 2:
            raise OSError(errno.EIO, "post-replace durability failure")

    monkeypatch.setattr(sidecar, "_fsync_directory", fail_only_post_replace)
    real_replace = sidecar.os.replace
    restore_attempts = 0

    def fail_restores(source_path, destination_path):
        nonlocal restore_attempts
        source_path = Path(source_path)
        destination_path = Path(destination_path)
        if destination_path == destination and ".restore-primary." in source_path.name:
            restore_attempts += 1
            raise OSError(errno.EIO, "primary restore failed")
        if (
            fallback_fails
            and destination_path == destination
            and ".restore-fallback." in source_path.name
        ):
            restore_attempts += 1
            raise OSError(errno.EIO, "fallback restore failed")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(sidecar.os, "replace", fail_restores)

    response = client.post(
        "/api/native-dialogs/save-as",
        json={
            "request_id": f"save-catastrophic-{int(fallback_fails)}",
            "artifact": str(source),
        },
        headers=_headers(token),
    )

    assert response.status_code == 409
    assert restore_attempts == 0
    assert source.read_text() == "new data"
    assert destination.read_text() == "new data"
    recovery_files = [
        path for path in chosen.iterdir() if path != destination and path.is_file()
    ]
    backup_preserved = any(path.read_bytes() == old_bytes for path in recovery_files)
    detail = response.json()["detail"]
    assert detail["code"] == "save_as_recovery_required"
    assert (
        detail["message"]
        == "Save As could not safely restore the previous destination. Manual recovery is required."
    )
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", detail["recovery_id"])
    assert str(tmp_path) not in response.text
    assert chosen.name not in response.text
    assert destination.name not in response.text
    assert all(path.name not in response.text for path in recovery_files)
    assert backup_preserved
