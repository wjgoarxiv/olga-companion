from __future__ import annotations

import errno
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


@dataclass(frozen=True, slots=True)
class SaveAsCase:
    source: Path
    destination: Path
    chosen: Path


def _case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: bool,
) -> SaveAsCase:
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"approved export")
    destination = chosen / "saved.csv"
    if existing:
        destination.write_bytes(b"initial destination")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    return SaveAsCase(source, destination, chosen)


def _post(case: SaveAsCase, token: str, request_id: str):
    return client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": request_id, "artifact": str(case.source)},
        headers=_headers(token),
    )


def _is_staging(path: Path, case: SaveAsCase) -> bool:
    return (
        path.parent == case.chosen
        and path.name.startswith(f".{case.destination.name}.")
        and path.suffix == ".tmp"
    )


def test_absent_publish_revalidates_after_private_stage_cleanup(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch, existing=False)
    real_unlink = Path.unlink
    mutated = False

    def mutate_during_stage_unlink(path: Path, *args, **kwargs):
        nonlocal mutated
        if _is_staging(path, case) and not mutated:
            mutated = True
            case.destination.write_bytes(b"concurrent winner")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", mutate_during_stage_unlink)

    response = _post(case, token, "save-post-check-mutation")

    assert mutated is True
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_concurrent_destination"
    assert case.destination.read_bytes() == b"concurrent winner"
    assert [path.name for path in case.chosen.iterdir()] == [case.destination.name]


def test_absent_publish_cleanup_eio_does_not_mask_typed_uncertain_error(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch, existing=False)
    real_unlink = Path.unlink
    cleanup_attempts = 0

    def fail_stage_unlink(path: Path, *args, **kwargs):
        nonlocal cleanup_attempts
        if _is_staging(path, case):
            cleanup_attempts += 1
            raise OSError(errno.EIO, "persistent private stage cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_stage_unlink)
    response = _post(case, token, "save-stage-cleanup-eio")
    retained = [path for path in case.chosen.iterdir() if path != case.destination]
    try:
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "save_as_publish_uncertain"
        assert cleanup_attempts >= 1
        assert case.destination.read_bytes() == b"approved export"
        assert len(retained) == 1 and _is_staging(retained[0], case)
        assert str(tmp_path) not in response.text
        assert retained[0].name not in response.text
    finally:
        for path in retained:
            real_unlink(path, missing_ok=True)


def test_restored_winner_cleanup_fsync_retains_winner_recovery(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    case = _case(tmp_path, monkeypatch, existing=True)
    winner = b"concurrent winner"
    expected_hash = hashlib.sha256(winner).hexdigest()
    real_replace = sidecar._replace_existing_with_prior
    replace_calls = 0
    fsync_calls = 0
    persisted: list[tuple[Path, str]] = []

    def inject_winner_before_replace(replacement: Path, destination: Path) -> Path:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            case.destination.write_bytes(winner)
        return real_replace(replacement, destination)

    def fail_winner_recovery_cleanup(parent: Path) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 4:
            raise OSError(errno.EIO, "winner recovery cleanup fsync failed")

    def capture_recovery(destination: Path, backup: Path, digest: str) -> str:
        persisted.append((backup, digest))
        return "winnerRecovery01"

    monkeypatch.setattr(
        sidecar, "_replace_existing_with_prior", inject_winner_before_replace
    )
    monkeypatch.setattr(sidecar, "_fsync_directory", fail_winner_recovery_cleanup)
    monkeypatch.setattr(sidecar.save_as_recovery, "persist", capture_recovery)

    response = _post(case, token, "save-winner-recovery-cleanup-fsync")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert case.destination.read_bytes() == winner
    assert replace_calls == 2 and fsync_calls >= 4
    assert len(persisted) == 1
    backup, digest = persisted[0]
    assert backup.is_file() and backup.read_bytes() == winner
    assert digest == expected_hash
    assert backup.name not in response.text


def test_existing_same_content_replacement_is_not_overwritten(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    case = _case(tmp_path, monkeypatch, existing=True)
    original_identity = (case.destination.stat().st_dev, case.destination.stat().st_ino)
    winner = case.chosen / "same-content-winner.csv"
    real_create_backup = sidecar._create_verified_backup
    winner_identity: tuple[int, int] | None = None

    def backup_then_replace(path: Path, expected_hash: str) -> Path:
        nonlocal winner_identity
        backup = real_create_backup(path, expected_hash)
        shutil.copy2(path, winner)
        os.replace(winner, path)
        winner_identity = (path.stat().st_dev, path.stat().st_ino)
        return backup

    monkeypatch.setattr(sidecar, "_create_verified_backup", backup_then_replace)

    response = _post(case, token, "save-existing-same-content-aba")

    current_identity = (case.destination.stat().st_dev, case.destination.stat().st_ino)
    assert winner_identity is not None and winner_identity != original_identity
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert current_identity == winner_identity
    assert case.destination.read_bytes() == b"initial destination"


def test_existing_same_content_commit_window_replacement_is_restored(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    case = _case(tmp_path, monkeypatch, existing=True)
    real_replace = sidecar._replace_existing_with_prior
    replace_calls = 0
    winner_identity: tuple[int, int] | None = None
    displaced_identity: tuple[int, int] | None = None

    def replace_after_same_content_aba(replacement: Path, destination: Path) -> Path:
        nonlocal replace_calls, winner_identity, displaced_identity
        replace_calls += 1
        if replace_calls == 1:
            winner = case.chosen / "commit-window-winner.csv"
            shutil.copy2(destination, winner)
            os.replace(winner, destination)
            winner_identity = (destination.stat().st_dev, destination.stat().st_ino)
        displaced = real_replace(replacement, destination)
        if replace_calls == 1:
            displaced_identity = (displaced.stat().st_dev, displaced.stat().st_ino)
        return displaced

    monkeypatch.setattr(
        sidecar, "_replace_existing_with_prior", replace_after_same_content_aba
    )

    response = _post(case, token, "save-existing-commit-window-aba")

    current_identity = (case.destination.stat().st_dev, case.destination.stat().st_ino)
    assert winner_identity is not None and displaced_identity == winner_identity
    assert response.status_code == 400
    assert replace_calls == 2
    assert current_identity == winner_identity
    assert case.destination.read_bytes() == b"initial destination"
    assert [path.name for path in case.chosen.iterdir()] == [case.destination.name]


def test_absent_publish_rejects_symlink_to_private_stage_replacement(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    case = _case(tmp_path, monkeypatch, existing=False)
    stage_name: str | None = None

    def replace_destination_with_stage_symlink(parent: Path) -> None:
        nonlocal stage_name
        stage = next(path for path in parent.iterdir() if _is_staging(path, case))
        stage_name = stage.name
        case.destination.unlink()
        case.destination.symlink_to(stage.name)

    monkeypatch.setattr(
        sidecar, "_fsync_directory", replace_destination_with_stage_symlink
    )

    response = _post(case, token, "save-stage-symlink-race")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_concurrent_destination"
    assert stage_name is not None
    assert os.path.lexists(case.destination) and case.destination.is_symlink()
    assert os.readlink(case.destination) == stage_name
    assert not (case.chosen / stage_name).exists()
