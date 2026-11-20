from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from olga_companion import native_dialogs

from native_dialog_api_test_support import _headers, client

pytest_plugins = ("native_dialog_api_test_fixtures",)


@dataclass(frozen=True, slots=True)
class ExistingCase:
    source: Path
    destination: Path
    chosen: Path


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ExistingCase:
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"approved export")
    destination = chosen / "saved.csv"
    destination.write_bytes(b"initial destination")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    return ExistingCase(source, destination, chosen)


def _post(case: ExistingCase, token: str, request_id: str):
    return client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": request_id, "artifact": str(case.source)},
        headers=_headers(token),
    )


def test_existing_post_commit_fsync_replacement_is_not_reported_success(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    case = _case(tmp_path, monkeypatch)
    winner = tmp_path / "post-commit-winner.csv"
    winner.write_bytes(b"concurrent winner after commit")
    fsync_calls = 0
    winner_identity: tuple[int, int] | None = None

    def replace_during_commit_fsync(parent: Path) -> None:
        nonlocal fsync_calls, winner_identity
        fsync_calls += 1
        if fsync_calls == 2:
            os.replace(winner, case.destination)
            metadata = case.destination.stat()
            winner_identity = metadata.st_dev, metadata.st_ino

    monkeypatch.setattr(sidecar, "_fsync_directory", replace_during_commit_fsync)

    response = _post(case, token, "save-existing-post-commit-race")

    metadata = case.destination.stat()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_concurrent_destination"
    assert fsync_calls == 2
    assert (metadata.st_dev, metadata.st_ino) == winner_identity
    assert case.destination.read_bytes() == b"concurrent winner after commit"
    assert case.source.read_bytes() == b"approved export"
    assert [path.name for path in case.chosen.iterdir()] == [case.destination.name]
    assert str(tmp_path) not in response.text


def test_restore_window_second_winner_is_restored_and_first_winner_is_recoverable(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    case = _case(tmp_path, monkeypatch)
    first_winner = b"first concurrent winner"
    second_winner = b"latest concurrent winner"
    real_replace = sidecar._replace_existing_with_prior
    replace_calls = 0
    second_identity: tuple[int, int] | None = None
    persisted: list[tuple[Path, str]] = []

    def inject_two_winners(replacement: Path, destination: Path) -> Path:
        nonlocal replace_calls, second_identity
        replace_calls += 1
        if replace_calls == 1:
            case.destination.write_bytes(first_winner)
        elif replace_calls == 2:
            winner = tmp_path / "latest-winner.csv"
            winner.write_bytes(second_winner)
            os.replace(winner, case.destination)
            metadata = case.destination.stat()
            second_identity = metadata.st_dev, metadata.st_ino
        return real_replace(replacement, destination)

    def capture_recovery(destination: Path, backup: Path, digest: str) -> str:
        persisted.append((backup, digest))
        return "twoWinnerRecovery"

    monkeypatch.setattr(sidecar, "_replace_existing_with_prior", inject_two_winners)
    monkeypatch.setattr(sidecar.save_as_recovery, "persist", capture_recovery)

    response = _post(case, token, "save-restore-window-second-winner")

    metadata = case.destination.stat()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert replace_calls == 3
    assert (metadata.st_dev, metadata.st_ino) == second_identity
    assert case.destination.read_bytes() == second_winner
    assert len(persisted) == 1
    recovery, _ = persisted[0]
    assert recovery.is_file() and recovery.read_bytes() == first_winner
    assert recovery.name not in response.text
    assert str(tmp_path) not in response.text


def test_post_commit_race_never_deletes_a_replaced_private_name(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    case = _case(tmp_path, monkeypatch)
    real_replace = sidecar._replace_existing_with_prior
    real_unlink = Path.unlink
    displaced: Path | None = None
    fsync_calls = 0
    unsafe_unlink_attempted = False
    persisted: list[Path] = []

    def record_displaced(replacement: Path, destination: Path) -> Path:
        nonlocal displaced
        displaced = real_replace(replacement, destination)
        return displaced

    def replace_public_and_private_during_fsync(parent: Path) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls != 2:
            return
        public_winner = tmp_path / "public-winner.csv"
        public_winner.write_bytes(b"public concurrent winner")
        os.replace(public_winner, case.destination)
        foreign_private = tmp_path / "foreign-private.csv"
        foreign_private.write_bytes(b"foreign private winner")
        assert displaced is not None
        os.replace(foreign_private, displaced)

    def reject_unsafe_unlink(path: Path, *args, **kwargs):
        nonlocal unsafe_unlink_attempted
        if displaced is not None and path == displaced:
            unsafe_unlink_attempted = True
        return real_unlink(path, *args, **kwargs)

    def capture_recovery(destination: Path, backup: Path, digest: str) -> str:
        persisted.append(backup)
        return "privateProofRecovery"

    monkeypatch.setattr(sidecar, "_replace_existing_with_prior", record_displaced)
    monkeypatch.setattr(
        sidecar, "_fsync_directory", replace_public_and_private_during_fsync
    )
    monkeypatch.setattr(Path, "unlink", reject_unsafe_unlink)
    monkeypatch.setattr(sidecar.save_as_recovery, "persist", capture_recovery)

    response = _post(case, token, "save-private-cleanup-proof-race")

    assert response.status_code == 409
    assert unsafe_unlink_attempted is False
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert case.destination.read_bytes() == b"public concurrent winner"
    assert displaced is not None and displaced.read_bytes() == b"foreign private winner"
    assert len(persisted) == 1
    assert (
        persisted[0].is_file() and persisted[0].read_bytes() == b"initial destination"
    )
    assert displaced.name not in response.text
    assert persisted[0].name not in response.text
    assert str(tmp_path) not in response.text
