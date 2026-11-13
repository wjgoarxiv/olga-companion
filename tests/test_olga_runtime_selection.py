from __future__ import annotations

from pathlib import Path

from olga_companion.olga_runtime import detect_olga as detect_runtime
from olga_runtime_test_support import _installed_release, _qualified_case


def test_case_evidence_selects_matching_installed_release(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0")
    _installed_release(installs, "2025.1.0")
    case = _qualified_case(tmp_path / "package", "2022.1.0")

    detection = detect_runtime(
        [
            str(installs / "OLGA*" / "opi.exe"),
            str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe"),
        ],
        environ={},
        source=case,
    )

    assert detection["detected"] is True
    assert detection["version"] == "2022.1.0"
    assert detection["kind"] == "engine"
    assert "OLGA 2022.1.0" in detection["exe"]
    assert detection["selection_status"] == "selected"
    assert detection["required_version"] == "2022.1.0"
    assert len(detection["candidates"]) == 4
    assert detection["evidence"][0]["source_type"] == "solver-out"


def test_missing_qualified_release_fails_closed_with_alternatives(
    tmp_path: Path,
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0")
    case = _qualified_case(tmp_path / "package", "2022.1.0")

    detection = detect_runtime(
        [
            str(installs / "OLGA*" / "opi.exe"),
            str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe"),
        ],
        environ={},
        source=case,
    )

    assert detection["detected"] is False
    assert detection["selection_status"] == "missing_required_version"
    assert detection["required_version"] == "2022.1.0"
    assert detection["exe"] is None
    assert {item["version"] for item in detection["alternatives"]} == {"2025.1.0"}


def test_no_case_evidence_uses_latest_semantic_release_and_lists_inventory(
    tmp_path: Path,
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.9.0", engine=False)
    _installed_release(installs, "2025.10.0", engine=False)

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
    )

    assert detection["detected"] is True
    assert detection["version"] == "2025.10.0"
    assert detection["selection_status"] == "selected_fallback"
    assert detection["rationale"] == (
        "No run record exists for this case; selected the newest installed OLGA (2025.10.0)."
    )
    assert [candidate["version"] for candidate in detection["candidates"]] == [
        "2025.10.0",
        "2025.9.0",
    ]


def test_no_evidence_prefers_direct_engine_over_newer_unsupported_opi(
    tmp_path: Path,
) -> None:
    installs = tmp_path / "installs"
    engine = Path(_installed_release(installs, "2022.1.0", opi=False)[0])
    opi = Path(_installed_release(installs, "2025.1.0", engine=False)[0])

    detection = detect_runtime(
        [
            str(installs / "OLGA*" / "opi.exe"),
            str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe"),
        ],
        environ={},
    )

    assert detection["exe"] == str(engine)
    assert detection["kind"] == "engine"
    assert detection["version"] == "2022.1.0"
    assert detection["rationale"] == (
        "No run record exists for this case; selected the newest installed direct OLGA engine (2022.1.0)."
    )
    assert any(item["exe"] == str(opi) for item in detection["alternatives"])


def test_no_evidence_same_version_prefers_direct_engine(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    paths = _installed_release(installs, "2025.1.0")

    detection = detect_runtime(
        [
            str(installs / "OLGA*" / "opi.exe"),
            str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe"),
        ],
        environ={},
    )

    assert detection["kind"] == "engine"
    assert detection["exe"] == next(path for path in paths if "OlgaExecutables" in path)


def test_duplicate_glob_matches_are_reported_once(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    paths = _installed_release(installs, "2025.1.0", engine=False)
    pattern = str(installs / "OLGA*" / "opi.exe")

    detection = detect_runtime([pattern, pattern], environ={})

    assert [item["exe"] for item in detection["candidates"]] == paths


def test_conflicting_qualified_result_versions_fail_closed(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0")
    _installed_release(installs, "2025.1.0")
    case = _qualified_case(tmp_path / "package", "2022.1.0")
    (case.parent / "case.tpl").write_text(
        "'OLGA 2025.1.0'\nTIME PLOT\nINPUT FILE\n'case.genkey'\n"
    )

    detection = detect_runtime(
        [str(installs / "OLGA*" / "opi.exe")],
        environ={},
        source=case,
    )

    assert detection["detected"] is False
    assert detection["selection_status"] == "conflicting_evidence"
    assert {item["version"] for item in detection["evidence"]} == {
        "2022.1.0",
        "2025.1.0",
    }


def test_mismatched_environment_override_cannot_bypass_qualified_version(
    tmp_path: Path,
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0")
    override = Path(_installed_release(installs, "2025.1.0", engine=False)[0])
    case = _qualified_case(tmp_path / "package", "2022.1.0")

    detection = detect_runtime(
        [
            str(installs / "OLGA*" / "opi.exe"),
            str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe"),
        ],
        environ={"OLGA_EXE_PATH": str(override)},
        source=case,
    )

    assert detection["detected"] is False
    assert detection["selection_status"] == "override_version_mismatch"
    assert detection["required_version"] == "2022.1.0"
    assert detection["version"] is None
    assert any(item["version"] == "2022.1.0" for item in detection["alternatives"])
