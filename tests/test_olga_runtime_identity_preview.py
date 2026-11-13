from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from olga_companion import runner
from olga_companion.olga_runtime import detect_olga as detect_runtime
from olga_runtime_test_support import _installed_release, _qualified_case


def test_discovered_candidates_have_stable_opaque_runtime_ids(tmp_path: Path) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2025.1.0", engine=False)
    pattern = str(installs / "OLGA*" / "opi.exe")

    first = detect_runtime([pattern], environ={})
    second = detect_runtime([pattern], environ={})

    candidate = first["candidates"][0]
    assert candidate["candidate_id"] == second["candidates"][0]["candidate_id"]
    assert candidate["runtime_id"] == candidate["candidate_id"]
    assert first["candidate_id"] == candidate["candidate_id"]
    assert first["runtime_id"] == candidate["candidate_id"]
    assert str(installs) not in candidate["candidate_id"]


def test_candidate_identity_hashes_executable_content_even_when_metadata_is_preserved(
    tmp_path: Path,
) -> None:
    executable = Path(_installed_release(tmp_path, "2025.1.0", engine=False)[0])
    pattern = str(tmp_path / "OLGA*" / "opi.exe")
    first = detect_runtime([pattern], environ={})
    original_stat = executable.stat()
    original = executable.read_bytes()
    replacement = bytes([original[0] ^ 1]) + original[1:]
    executable.write_bytes(replacement)
    os.utime(executable, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    second = detect_runtime([pattern], environ={})

    assert first["candidate_id"] != second["candidate_id"]
    assert first["sha256"] == hashlib.sha256(original).hexdigest()
    assert second["sha256"] == hashlib.sha256(replacement).hexdigest()


def test_preview_resolves_requested_candidate_from_fresh_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installs = tmp_path / "installs"
    older = Path(_installed_release(installs, "2022.1.0", opi=False)[0])
    _installed_release(installs, "2025.1.0", opi=False)
    pattern = str(installs / "OLGA*" / "OlgaExecutables" / "OLGA-*.exe")
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n")
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [pattern])
    monkeypatch.setattr(
        runner, "_validate_case", lambda _path: {"valid": True, "command": {}}
    )
    monkeypatch.setattr(
        runner,
        "ensure_broker",
        lambda: SimpleNamespace(
            to_dict=lambda: {"protocol": "test", "sha256": "b" * 64}
        ),
    )
    inventory = runner.detect_olga(case)
    older_id = next(
        item["candidate_id"]
        for item in inventory["candidates"]
        if item["exe"] == str(older)
    )

    preview = runner.preview_run(str(case), candidate_id=older_id)

    assert preview["candidate_id"] == older_id
    assert preview["detection"]["version"] == "2022.1.0"
    older.unlink()
    with pytest.raises(ValueError, match="candidate|runtime|fresh|available"):
        runner.preview_run(str(case), candidate_id=older_id)


def test_preview_rejects_candidate_id_after_executable_identity_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installs = tmp_path / "installs"
    executable = Path(_installed_release(installs, "2025.1.0", engine=False)[0])
    pattern = str(installs / "OLGA*" / "opi.exe")
    case = tmp_path / "case.genkey"
    case.write_text("CASE LABEL=case\nENDCASE\n")
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [pattern])
    monkeypatch.setattr(
        runner, "_validate_case", lambda _path: {"valid": True, "command": {}}
    )
    candidate_id = runner.detect_olga(case)["candidate_id"]

    executable.write_text("replacement executable payload")

    with pytest.raises(ValueError, match="candidate|runtime|fresh|available"):
        runner.preview_run(str(case), candidate_id=candidate_id)


def test_preview_rejects_candidate_that_mismatches_required_case_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installs = tmp_path / "installs"
    _installed_release(installs, "2022.1.0", engine=False)
    _installed_release(installs, "2025.1.0", engine=False)
    pattern = str(installs / "OLGA*" / "opi.exe")
    case = _qualified_case(tmp_path / "package", "2022.1.0")
    monkeypatch.delenv("OLGA_EXE_PATH", raising=False)
    monkeypatch.setattr(runner, "OLGA_EXE_GLOBS", [pattern])
    inventory = runner.detect_olga(case)
    wrong_id = next(
        item["candidate_id"]
        for item in inventory["candidates"]
        if item["version"] == "2025.1.0"
    )

    with pytest.raises(ValueError, match="requires OLGA 2022.1.0"):
        runner.preview_run(str(case), candidate_id=wrong_id)
