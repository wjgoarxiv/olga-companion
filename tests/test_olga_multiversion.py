"""T9 RED: every installed OLGA release is detected, old numbers parse, and a
manual executable overrides autodetection."""
from __future__ import annotations

from pathlib import Path

import pytest

from olga_companion import olga_runtime_paths as paths
from olga_companion import olga_runtime_versions as versions
from olga_companion.olga_runtime import detect_olga as detect_runtime
from olga_runtime_test_support import _installed_release, _qualified_case

RELEASES = ["2014.1", "2017.2", "2019.1", "2021.1", "2022.1", "2023.1", "2024.2"]


def _program_tree(root: Path, vendor: str, release: str) -> list[str]:
    install = root / "Program Files" / vendor
    return _installed_release(install, f"{release}.0")


def test_path_version_reads_legacy_seven() -> None:
    release, key = versions.path_version(r"C:\Program Files\Schlumberger\OLGA 7.3.5\bin\opi.exe")
    assert release == "7.3.5"
    assert key == (7, 3, 5)
    release, key = versions.path_version("/mnt/c/Program Files/SLB/OLGA 7.3.5/opi.exe")
    assert release == "7.3.5"
    assert key == (7, 3, 5)


def test_legacy_seven_sorts_below_modern() -> None:
    from olga_companion.olga_runtime import _candidate_sort_key as sort_key

    old = {"_version_key": (7, 3, 5), "kind": "opi", "exe": "b"}
    new = {"_version_key": (2014, 1, 0), "kind": "opi", "exe": "a"}
    assert sort_key(old) > sort_key(new)


def test_multiversion_tree_detects_all_releases(tmp_path: Path) -> None:
    drive_c = tmp_path / "c"
    drive_d = tmp_path / "d"
    for release in RELEASES:
        _program_tree(drive_c, "Schlumberger", release)
    _program_tree(drive_c, "SLB", "2022.1")
    _program_tree(drive_d, "Schlumberger", "2024.2")
    decoy = drive_c / "Program Files" / "Schlumberger" / "OLGA-S" / "opi.exe"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("stub")

    patterns = [
        str(drive_c / "Program Files" / "*" / "OLGA*" / "opi.exe"),
        str(drive_d / "Program Files" / "*" / "OLGA*" / "opi.exe"),
    ]
    detection = detect_runtime(patterns, environ={})

    found = {item["version"] for item in detection["candidates"]}
    assert {f"{release}.0" for release in RELEASES} <= found
    assert not any("OLGA-S" in item["exe"] for item in detection["candidates"])
    assert detection["detected"] is True


def test_case_evidence_selects_matching_old_release(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2019.1.0")
    _installed_release(installs, "2024.2.0")
    case = _qualified_case(tmp_path / "package", "2019.1.0")

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
        source=case,
    )

    assert detection["detected"] is True
    assert detection["version"] == "2019.1.0"
    assert detection["required_version"] == "2019.1.0"


def test_registry_reader_adds_install_locations(tmp_path: Path) -> None:
    from olga_companion import olga_runtime_detection as detection_module

    installs = tmp_path / "reg"
    _installed_release(installs, "2024.2.0")

    def fake_reader():
        return [
            ("OLGA 2024.2", str(installs / "OLGA 2024.2.0")),
            ("OLGA-S 2024.2", str(installs / "OLGA-S")),
            ("Not OLGA", str(installs)),
        ]

    locations = detection_module.registry_install_locations(reader=fake_reader)
    assert locations == [str(installs / "OLGA 2024.2.0")]

    detection = detect_runtime([], environ={}, registry_reader=fake_reader)
    assert detection["detected"] is True
    # Engine kind outranks opi: the detected install's direct engine is selected.
    assert detection["exe"] == str(installs / "OLGA 2024.2.0" / "OlgaExecutables" / "OLGA-2024.2.0.exe")
    assert detection["source"] == "registry"


def test_windows_fixed_drives_skip_network_and_removable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes

    types = {"C:\\": 3, "D:\\": 4, "E:\\": 2, "F:\\": 5}

    class _Kernel:
        @staticmethod
        def GetDriveTypeW(root: str) -> int:
            return types.get(root, 1)

    class _Windll:
        kernel32 = _Kernel()

    monkeypatch.setattr(ctypes, "windll", _Windll(), raising=False)
    assert paths._windows_fixed_drives() == ["C"]
    assert paths._existing_drive_letters() == ["C"]

    class _Exploding:
        @property
        def kernel32(self):
            raise OSError("no win32 here")

    monkeypatch.setattr(ctypes, "windll", _Exploding(), raising=False)
    assert paths._windows_fixed_drives() == []


def test_registry_location_with_glob_chars_is_escaped(tmp_path: Path) -> None:
    from olga_companion import olga_runtime_detection as detection_module

    installs = tmp_path / "weird[12]"
    _installed_release(installs, "2024.2.0")

    def fake_reader():
        return [("OLGA 2024.2", str(installs / "OLGA 2024.2.0"))]

    locations = detection_module.registry_install_locations(reader=fake_reader)
    assert locations == [str(installs / "OLGA 2024.2.0")]
    detection = detect_runtime([], environ={}, registry_reader=fake_reader)
    assert detection["detected"] is True
    assert detection["source"] == "registry"


def test_broken_symlink_candidate_does_not_abort_detection(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0")
    haunted = installs / "OLGA 2099.9.0"
    haunted.mkdir(parents=True)
    (haunted / "opi.exe").symlink_to(tmp_path / "missing-target.exe")

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")], environ={}
    )

    assert detection["detected"] is True
    assert detection["version"] == "2022.1.0"


def test_sha256_reads_content_despite_preserved_metadata(tmp_path: Path) -> None:
    import os

    from olga_companion import olga_runtime_detection as detection_module

    exe = tmp_path / "opi.exe"
    exe.write_bytes(b"content-a")
    first = detection_module.executable_sha256(exe)
    stat = exe.stat()
    exe.write_bytes(b"content-b")
    os.utime(exe, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert detection_module.executable_sha256(exe) != first


def test_stale_manual_override_falls_through_with_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0")
    ghost = installs / "ghost" / "opi.exe"
    ghost.parent.mkdir(parents=True)
    ghost.write_text("stub")
    _save_override(str(ghost))
    ghost.unlink()

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")], environ={}
    )

    assert detection["detected"] is True
    assert detection["exe"] != str(ghost)
    assert "manually chosen OLGA executable was not found" in detection["rationale"]
    assert detection["reason_params"].get("stale_manual_override") is True


def test_save_rejects_non_exe(tmp_path: Path) -> None:
    from olga_companion import config

    script = tmp_path / "run.sh"
    script.write_text("stub", encoding="utf-8")
    with pytest.raises(ValueError):
        config.save_olga_exe_override({"exe": str(script)})


def test_drive_expansion_covers_existing_drives_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        paths, "_existing_drive_letters", lambda: ["C", "D", "Z"]
    )
    globs = paths.default_exe_globs()
    assert any(g.startswith("C:/") for g in globs)
    assert any(g.startswith("D:/") for g in globs)
    assert any(g.startswith("Z:/") for g in globs)
    assert any("/mnt/d/" in g for g in globs)
    assert not any(g.startswith("A:/") or g.startswith("B:/") for g in globs)
    assert all("OLGA-S" not in g for g in globs)


def _save_override(exe: str) -> None:
    from olga_companion import config

    # The override path is isolated per test by conftest.
    config.save_olga_exe_override({"exe": exe})


def test_manual_override_beats_autodetect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2024.2.0")
    manual = installs / "custom" / "opi.exe"
    manual.parent.mkdir(parents=True)
    manual.write_text("stub")
    _save_override(str(manual))

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")], environ={}
    )

    assert detection["detected"] is True
    assert detection["exe"] == str(manual)
    assert detection["selection_status"] == "selected_override"
    assert detection["source"] == "manual:settings"


def test_env_override_still_beats_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2024.2.0")
    manual = installs / "custom" / "opi.exe"
    manual.parent.mkdir(parents=True)
    manual.write_text("stub")
    _save_override(str(manual))
    env_exe = installs / "OLGA 2024.2.0" / "opi.exe"

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={"OLGA_EXE_PATH": str(env_exe)},
    )

    assert detection["exe"] == str(env_exe)
    assert detection["source"] == "env:OLGA_EXE_PATH"


def test_manual_override_missing_file_is_not_found(tmp_path: Path) -> None:
    from olga_companion import config

    with pytest.raises(ValueError):
        config.save_olga_exe_override({"exe": str(tmp_path / "missing.exe")})
