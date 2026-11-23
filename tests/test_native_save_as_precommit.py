from __future__ import annotations

import errno
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


@pytest.mark.parametrize("destination_exists", [False, True])
def test_save_as_directory_fsync_eio_reports_the_safe_visible_state(
    token: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    destination_exists: bool,
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_text("new data")
    destination = chosen / "saved.csv"
    if destination_exists:
        destination.write_text("old data")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    real_fsync = sidecar.os.fsync
    calls = 0

    def fail_directory_fsync(fd: int):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EIO, "injected directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(sidecar.os, "fsync", fail_directory_fsync)

    response = client.post(
        "/api/native-dialogs/save-as",
        json={
            "request_id": f"save-dir-fsync-{int(destination_exists)}",
            "artifact": str(source),
        },
        headers=_headers(token),
    )

    assert source.read_text() == "new data"
    if destination_exists:
        assert response.status_code == 400
        assert destination.read_text() == "old data"
    else:
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "save_as_publish_uncertain"
        assert destination.read_text() == "new data"
    assert not [path for path in chosen.iterdir() if path.name != destination.name]


@pytest.mark.parametrize("destination_exists", [False, True])
@pytest.mark.parametrize("failure", ["copy", "file-fsync", "replace"])
def test_save_as_precommit_failures_preserve_existing_destination_and_clean_residue(
    token: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    destination_exists: bool,
) -> None:
    import olga_companion.sidecar as sidecar

    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_text("new data")
    destination = chosen / "saved.csv"
    if destination_exists:
        destination.write_text("old data")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    if failure == "copy":
        monkeypatch.setattr(
            sidecar.shutil,
            "copyfileobj",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError(errno.EIO, "copy failed")
            ),
        )
    elif failure == "file-fsync":
        monkeypatch.setattr(
            sidecar.os,
            "fsync",
            lambda fd: (_ for _ in ()).throw(OSError(errno.EIO, "file fsync failed")),
        )
    else:
        if destination_exists:
            monkeypatch.setattr(
                sidecar,
                "_replace_existing_with_prior",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    OSError(errno.EIO, "replace failed")
                ),
            )
        else:
            monkeypatch.setattr(
                sidecar.os,
                "link",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    OSError(errno.EIO, "no-clobber publish failed")
                ),
            )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={
            "request_id": f"save-failure-{failure}-{int(destination_exists)}",
            "artifact": str(source),
        },
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert source.read_text() == "new data"
    if destination_exists:
        assert destination.read_text() == "old data"
        assert [path.name for path in chosen.iterdir()] == [destination.name]
    else:
        assert not destination.exists()
        assert list(chosen.iterdir()) == []


def test_save_as_backup_creation_failure_never_mutates_existing_destination(
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
    monkeypatch.setattr(
        sidecar,
        "_create_verified_backup",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError(errno.EIO, "backup creation failed")
        ),
        raising=False,
    )

    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-backup-create-fail", "artifact": str(source)},
        headers=_headers(token),
    )

    assert response.status_code == 400
    assert source.read_text() == "new data"
    assert destination.read_text() == "old data"
    assert [path.name for path in chosen.iterdir()] == [destination.name]
