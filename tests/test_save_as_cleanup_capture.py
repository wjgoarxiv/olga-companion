from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from olga_companion.save_as_atomic import regular_file_identity
from olga_companion.sidecar_save_as_cleanup import cleanup_existing_private
from olga_companion.sidecar_save_as_files import SaveAsRecoveryRequiredError


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_private_cleanup_captures_owned_name_before_deleting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "saved.csv"
    displaced = tmp_path / ".saved.csv.displaced.bak"
    backup = tmp_path / ".saved.csv.recovery.bak"
    destination.write_bytes(b"approved export")
    displaced.write_bytes(b"previous destination")
    backup.write_bytes(b"previous destination")
    displaced_identity = regular_file_identity(displaced)
    backup_identity = regular_file_identity(backup)
    assert displaced_identity is not None and backup_identity is not None
    digest = _digest(displaced)
    real_replace = os.replace

    def replace_then_install_foreign(source: Path, target: Path) -> None:
        real_replace(source, target)
        if source == displaced:
            displaced.write_bytes(b"foreign concurrent file")

    monkeypatch.setattr(os, "replace", replace_then_install_foreign)

    with pytest.raises(SaveAsRecoveryRequiredError):
        cleanup_existing_private(
            destination,
            displaced,
            displaced_identity,
            digest,
            backup,
            backup_identity,
            digest,
        )

    assert displaced.read_bytes() == b"foreign concurrent file"
    assert backup.read_bytes() == b"previous destination"


def test_mismatched_capture_survives_restore_link_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "saved.csv"
    displaced = tmp_path / ".saved.csv.displaced.bak"
    backup = tmp_path / ".saved.csv.recovery.bak"
    destination.write_bytes(b"approved export")
    displaced.write_bytes(b"previous destination")
    backup.write_bytes(b"previous destination")
    displaced_identity = regular_file_identity(displaced)
    backup_identity = regular_file_identity(backup)
    assert displaced_identity is not None and backup_identity is not None
    digest = _digest(displaced)
    captured_paths: list[Path] = []
    real_replace = os.replace
    real_link = os.link

    def replace_then_corrupt_capture(source: Path, target: Path) -> None:
        real_replace(source, target)
        if source == displaced:
            captured_paths.append(target)
            target.write_bytes(b"captured foreign file")

    def link_then_replace_restored_name(source: Path, target: Path) -> None:
        real_link(source, target)
        if target == displaced:
            newer = tmp_path / "newer-private-entry"
            newer.write_bytes(b"newer foreign file")
            real_replace(newer, target)

    monkeypatch.setattr(os, "replace", replace_then_corrupt_capture)
    monkeypatch.setattr(os, "link", link_then_replace_restored_name)

    with pytest.raises(SaveAsRecoveryRequiredError):
        cleanup_existing_private(
            destination,
            displaced,
            displaced_identity,
            digest,
            backup,
            backup_identity,
            digest,
        )

    assert displaced.read_bytes() == b"newer foreign file"
    assert captured_paths[0].read_bytes() == b"captured foreign file"
    assert backup.read_bytes() == b"previous destination"


def test_matched_capture_replacement_during_second_capture_survives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "saved.csv"
    displaced = tmp_path / ".saved.csv.displaced.bak"
    backup = tmp_path / ".saved.csv.recovery.bak"
    destination.write_bytes(b"approved export")
    displaced.write_bytes(b"previous destination")
    backup.write_bytes(b"previous destination")
    displaced_identity = regular_file_identity(displaced)
    backup_identity = regular_file_identity(backup)
    assert displaced_identity is not None and backup_identity is not None
    digest = _digest(displaced)
    captured_displaced: Path | None = None
    captured_backup: Path | None = None
    real_replace = os.replace

    def replace_first_capture_during_second(source: Path, target: Path) -> None:
        nonlocal captured_displaced, captured_backup
        real_replace(source, target)
        if source == displaced:
            captured_displaced = target
        elif source == backup:
            captured_backup = target
            assert captured_displaced is not None
            foreign = tmp_path / "foreign-captured-replacement"
            foreign.write_bytes(b"foreign captured replacement")
            real_replace(foreign, captured_displaced)

    monkeypatch.setattr(os, "replace", replace_first_capture_during_second)

    cleanup_existing_private(
        destination,
        displaced,
        displaced_identity,
        digest,
        backup,
        backup_identity,
        digest,
    )

    assert captured_displaced is not None and captured_backup is not None
    assert captured_displaced.read_bytes() == b"foreign captured replacement"
    assert captured_backup.read_bytes() == b"previous destination"
    assert not displaced.exists()
    assert not backup.exists()


def test_capture_hardens_retained_file_before_ownership_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olga_companion import sidecar_save_as_cleanup as cleanup

    source = tmp_path / ".saved.csv.displaced.bak"
    retention = tmp_path / ".olga-companion-retained-test"
    retention.mkdir()
    source.write_bytes(b"previous destination")
    identity = regular_file_identity(source)
    assert identity is not None
    digest = _digest(source)
    hardened: list[Path] = []
    real_matches = cleanup.file_matches

    def matches_after_hardening(
        path: Path,
        expected_identity: tuple[int, int, int],
        expected_hash: str,
    ) -> bool:
        assert hardened == [path]
        return real_matches(path, expected_identity, expected_hash)

    monkeypatch.setattr(
        cleanup,
        "harden_private_path",
        lambda path, *, directory: hardened.append(path),
        raising=False,
    )
    monkeypatch.setattr(cleanup, "file_matches", matches_after_hardening)

    captured = cleanup._capture_owned_name(source, identity, digest, retention)

    assert captured is not None
    assert hardened == [captured]


@pytest.mark.parametrize("failure_call", [1, 2])
def test_capture_hardening_failure_reports_existing_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_call: int,
) -> None:
    from olga_companion import sidecar_save_as_cleanup as cleanup

    destination = tmp_path / "saved.csv"
    displaced = tmp_path / ".saved.csv.displaced.bak"
    backup = tmp_path / ".saved.csv.recovery.bak"
    destination.write_bytes(b"approved export")
    displaced.write_bytes(b"previous destination")
    backup.write_bytes(b"previous destination")
    displaced_identity = regular_file_identity(displaced)
    backup_identity = regular_file_identity(backup)
    assert displaced_identity is not None and backup_identity is not None
    digest = _digest(displaced)
    hardening_calls = 0

    def fail_second_hardening(path: Path, *, directory: bool) -> None:
        nonlocal hardening_calls
        del path, directory
        hardening_calls += 1
        if hardening_calls == failure_call:
            raise OSError("capture ACL failure")

    monkeypatch.setattr(cleanup, "harden_private_path", fail_second_hardening)

    with pytest.raises(SaveAsRecoveryRequiredError) as raised:
        cleanup_existing_private(
            destination,
            displaced,
            displaced_identity,
            digest,
            backup,
            backup_identity,
            digest,
        )

    recovery = raised.value.backup_path
    assert hardening_calls == failure_call
    assert recovery.is_file()
    assert recovery.read_bytes() == b"previous destination"
    assert _digest(recovery) == raised.value.expected_hash
