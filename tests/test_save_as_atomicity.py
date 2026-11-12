from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olga_companion import native_dialogs
from olga_companion.agent import session_token
from olga_companion.sidecar import app


client = TestClient(app)


@dataclass(frozen=True, slots=True)
class SaveAsFixture:
    source: Path
    destination: Path
    chosen: Path


@pytest.fixture
def token() -> str:
    return session_token.boot_token()


def _headers(token: str) -> dict[str, str]:
    return {"X-Session-Token": token}


def _save_as_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: bool,
) -> SaveAsFixture:
    exports = tmp_path / "exports"
    chosen = tmp_path / "chosen"
    exports.mkdir()
    chosen.mkdir()
    source = exports / "artifact.csv"
    source.write_bytes(b"approved export")
    destination = chosen / "raced.csv"
    if existing:
        destination.write_bytes(b"initial destination")
    monkeypatch.setattr("olga_companion.results.exports_root", lambda: exports)
    monkeypatch.setattr(
        native_dialogs,
        "show_dialog",
        lambda *args, **kwargs: {"status": "selected", "path": str(destination)},
    )
    return SaveAsFixture(source=source, destination=destination, chosen=chosen)


def test_save_as_absent_in_place_mutation_during_publish_is_not_success(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    # Given an absent destination and the real hardlink publication path.
    case = _save_as_fixture(tmp_path, monkeypatch, existing=False)
    shared_inode_observed = False

    def mutate_during_publish_fsync(parent: Path) -> None:
        nonlocal shared_inode_observed
        private_paths = [path for path in parent.iterdir() if path != case.destination]
        assert len(private_paths) == 1
        shared_inode_observed = os.path.samefile(private_paths[0], case.destination)
        case.destination.write_bytes(b"concurrent winner")

    monkeypatch.setattr(sidecar, "_fsync_directory", mutate_during_publish_fsync)

    # When another actor mutates the published inode before durability returns.
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-absent-in-place-race", "artifact": str(case.source)},
        headers=_headers(token),
    )

    # Then success is rejected without removing or replacing the concurrent bytes.
    assert shared_inode_observed is True
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_concurrent_destination"
    assert case.destination.read_bytes() == b"concurrent winner"
    assert case.source.read_bytes() == b"approved export"
    assert [path.name for path in case.chosen.iterdir()] == [case.destination.name]


def test_save_as_absent_fsync_failure_never_unlinks_a_concurrent_winner(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    # Given
    case = _save_as_fixture(tmp_path, monkeypatch, existing=False)
    winner = tmp_path / "concurrent-winner.csv"
    winner.write_bytes(b"concurrent winner")
    unsafe_unlink_attempted = False
    real_unlink = Path.unlink

    def fail_publish_fsync(parent: Path) -> None:
        raise OSError(errno.EIO, f"injected fsync failure for {parent}")

    def race_before_rollback_unlink(path: Path, *args, **kwargs):
        nonlocal unsafe_unlink_attempted
        if path == case.destination:
            unsafe_unlink_attempted = True
            os.replace(winner, case.destination)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(sidecar, "_fsync_directory", fail_publish_fsync)
    monkeypatch.setattr(Path, "unlink", race_before_rollback_unlink)

    # When
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-absent-fsync-race", "artifact": str(case.source)},
        headers=_headers(token),
    )
    if not unsafe_unlink_attempted:
        os.replace(winner, case.destination)

    # Then
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_publish_uncertain"
    assert unsafe_unlink_attempted is False
    assert case.destination.read_bytes() == b"concurrent winner"
    assert case.source.read_bytes() == b"approved export"
    assert [path.name for path in case.chosen.iterdir()] == [case.destination.name]
    assert str(tmp_path) not in response.text
    assert case.destination.name not in response.text


def test_save_as_cleanup_failure_after_concurrent_restore_never_rolls_back_winner(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    # Given
    case = _save_as_fixture(tmp_path, monkeypatch, existing=True)
    real_replace = sidecar._replace_existing_with_prior
    real_os_replace = os.replace
    attempts = 0
    discarded: Path | None = None
    cleanup_failures = 0

    def concurrent_replace(replacement: Path, target: Path) -> Path:
        nonlocal attempts, discarded
        attempts += 1
        if attempts == 1:
            case.destination.write_bytes(b"concurrent winner")
        result = real_replace(replacement, target)
        if attempts == 2:
            discarded = result
        return result

    def fail_first_cleanup_capture(source: Path, target: Path) -> None:
        nonlocal cleanup_failures
        if (
            discarded is not None
            and Path(target).parent.name.startswith(".olga-companion-retained-")
            and cleanup_failures == 0
        ):
            cleanup_failures += 1
            raise OSError(errno.EIO, "discarded export capture failed")
        real_os_replace(source, target)

    monkeypatch.setattr(sidecar, "_replace_existing_with_prior", concurrent_replace)
    monkeypatch.setattr(os, "replace", fail_first_cleanup_capture)

    # When
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-restored-cleanup-race", "artifact": str(case.source)},
        headers=_headers(token),
    )

    # Then
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert attempts == 2
    assert cleanup_failures == 1
    assert case.destination.read_bytes() == b"concurrent winner"
    retained = [path for path in case.chosen.iterdir() if path != case.destination]
    assert any(path.read_bytes() == b"initial destination" for path in retained)
    assert all(path.name.startswith(".") for path in retained)
    assert all(path.name not in response.text for path in retained)


def test_save_as_snapshots_existing_destination_before_source_staging(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    # Given
    case = _save_as_fixture(tmp_path, monkeypatch, existing=True)
    real_sha256 = sidecar._sha256
    destination_mutated = False

    def mutate_when_source_staging_starts(path: Path) -> str:
        nonlocal destination_mutated
        if path == case.source and not destination_mutated:
            destination_mutated = True
            case.destination.write_bytes(b"concurrent winner")
        return real_sha256(path)

    monkeypatch.setattr(sidecar, "_sha256", mutate_when_source_staging_starts)

    # When
    response = client.post(
        "/api/native-dialogs/save-as",
        json={
            "request_id": "save-baseline-before-staging",
            "artifact": str(case.source),
        },
        headers=_headers(token),
    )

    # Then
    assert destination_mutated is True
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert case.destination.read_bytes() == b"concurrent winner"
    assert case.source.read_bytes() == b"approved export"


def test_save_as_post_publish_failure_never_rolls_back_a_concurrent_winner(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import olga_companion.sidecar as sidecar

    # Given
    case = _save_as_fixture(tmp_path, monkeypatch, existing=True)
    winner = tmp_path / "concurrent-winner.csv"
    winner.write_bytes(b"concurrent winner")
    directory_fsyncs = 0

    def replace_winner_then_fail(parent: Path) -> None:
        nonlocal directory_fsyncs
        directory_fsyncs += 1
        if directory_fsyncs == 2:
            os.replace(winner, case.destination)
            raise OSError(errno.EIO, f"post-publish fsync failed for {parent}")

    monkeypatch.setattr(sidecar, "_fsync_directory", replace_winner_then_fail)

    # When
    response = client.post(
        "/api/native-dialogs/save-as",
        json={"request_id": "save-post-publish-winner", "artifact": str(case.source)},
        headers=_headers(token),
    )

    # Then
    assert directory_fsyncs >= 2
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "save_as_recovery_required"
    assert case.destination.read_bytes() == b"concurrent winner"
    assert case.source.read_bytes() == b"approved export"
